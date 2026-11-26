// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.
//
// Derived from pyodide (src/core/stack_switching/pystate.c and
// pystate_pycore.c, release 314.0.8), modified for pyjs. See
// src/js/stack_state.ts for the other half (the C stack in linear memory) and
// src/stack_switching_README.md for what was taken from where.
//
// ---------------------------------------------------------------------------
// WHAT THIS IS FOR: several Python call stacks suspended at the same time.
//
// With JSPI, Python code can wait for a JavaScript promise (`run_sync`): the
// browser suspends the WebAssembly call stack and the event loop keeps running.
// Other Python code then runs, and may itself suspend. Each of these "tasks"
// (a Python call entered from JavaScript through `pyjs_call_promising`) must
// be resumable later, in ANY order, without disturbing the others.
//
// The browser only takes care of the wasm call stack itself. Two more things
// that a running Python call uses are shared by all tasks and strictly LIFO:
//   1. emscripten's stack in linear memory (C locals, CPython's C frames):
//      handled in src/js/stack_state.ts (moved out of the way and back)
//   2. CPython's thread state: the chain of Python frames, the memory they
//      live in (the "data stack"), the exception being handled, the
//      contextvars context, the recursion counter, asyncio's current task:
//      handled HERE
//
// There is exactly one PyThreadState and it stays the current one. Each task
// owns the per-task fields listed in TaskState; when we switch tasks, these
// fields are swapped in and out of the thread state. Everything else on the
// thread state is shared. (The approach of greenlet, see
// https://github.com/python-greenlet/greenlet/blob/master/src/greenlet/TPythonState.cpp)
//
// Who calls what:
//   pyjs_enter_promising_task / pyjs_exit_promising_task
//       from pyjs_call_promising (src/py_entry.cpp), around the Python call
//   pyjs_capture_task_state / pyjs_restore_task_state
//       from JavaScript (jspiAwait in src/js/jsops.ts), right before the task
//       suspends in run_sync and right after it resumed
//
// AUDIT ON EVERY PYTHON UPDATE: the fields of PyThreadState /
// _PyThreadStateImpl change between versions; each new field must be
// classified as per-task or shared (greenlet's list is a good guide).
// Written for CPython 3.14.
// ---------------------------------------------------------------------------

// The internal headers (for _PyThreadStateImpl and the data stack) require
// Py_BUILD_CORE_MODULE.
#define Py_BUILD_CORE_MODULE 1

// pycore_obmalloc.h uses `bool` without including stdbool.h itself.
#include <stdbool.h>
#include <stdlib.h>
#include <string.h>

#include "Python.h"
#include "internal/pycore_obmalloc.h"
#include "internal/pycore_tstate.h"

#include <emscripten.h>

// ---------------------------------------------------------------------------
// two helpers that need the internal headers
// ---------------------------------------------------------------------------

// asyncio records the task whose step is currently executing on the thread
// state. That is per-task state: swapped in and out when we switch tasks.
// Returns the old value (a strong reference or NULL) and steals a reference to
// `task`.
static PyObject*
swap_asyncio_running_task(PyThreadState* tstate, PyObject* task)
{
    _PyThreadStateImpl* impl = (_PyThreadStateImpl*)tstate;
    PyObject* old = impl->asyncio_running_task;
    impl->asyncio_running_task = task;
    return old;
}

// Free a chain of data stack chunks (the memory Python frames live in). This
// mirrors clear_datastack() in CPython's pystate.c. Each task starts with
// datastack_chunk == NULL, so the frame allocator gives it a root chunk of its
// own, which is never popped and which we free when the task finishes.
static void
free_datastack(_PyStackChunk* chunk)
{
    while (chunk != NULL)
    {
        _PyStackChunk* prev = chunk->previous;
        _PyObject_VirtualFree(chunk, chunk->size);
        chunk = prev;
    }
}

// ---------------------------------------------------------------------------
// the per-task part of the thread state
// ---------------------------------------------------------------------------
typedef struct
{
    // The contextvars context. Strong reference.
    PyObject* context;
    // Top of the frame chain. The frames live on the data stack below, except
    // for the _PyEntryFrame that _PyEval_EvalFrameDefault keeps as a C local
    // (on the C stack, which stack_state.ts handles).
    struct _PyInterpreterFrame* current_frame;
    // The exception stack. exc_info is NULL if it pointed at tstate->exc_state,
    // since that address belongs to the thread state and not to the task.
    _PyErr_StackItem* exc_info;
    _PyErr_StackItem exc_state;
    // The exception being raised. Strong reference. Should be NULL when we
    // switch, but it is saved anyway so a stray exception cannot leak between
    // tasks.
    PyObject* current_exception;
    int py_recursion_remaining;
    // Depth of the trace / profile callbacks currently running.
    int tracing;
    // The sys.monitoring event currently being dispatched, or -1.
    int what_event;
    // Trashcan state: a chain of objects awaiting deallocation. Borrowed (the
    // objects have a refcount of 0 and are owned by the chain).
    PyObject* delete_later;
    // Memory for the frames. Each task starts with datastack_chunk == NULL, so
    // the frame allocator gives it a root chunk of its own.
    _PyStackChunk* datastack_chunk;
    PyObject** datastack_top;
    PyObject** datastack_limit;
    // JIT executor. Borrowed, always NULL here (no JIT in wasm).
    PyObject* current_executor;
    // _PyThreadStateImpl.asyncio_running_task. Strong reference.
    PyObject* asyncio_running_task;
} TaskState;

// Whether a promising task is executing right now. When true, `outer` holds
// the state of the code the task took over from (the "event loop level"),
// restored when the task suspends or finishes. A task is only ever started or
// resumed from the event loop (never from inside another running task), see
// stack_state.ts / callPythonPromising.
static bool in_task = false;
static TaskState outer;

// Move the per-task fields out of the thread state into `dst`. The thread
// state is left inconsistent: the caller follows up with load_task_state() or
// init_fresh_task().
static void
save_task_state(PyThreadState* tstate, TaskState* dst)
{
    dst->context = tstate->context;
    dst->current_frame = tstate->current_frame;
    // exc_info is the head of a linked list of _PyErr_StackItems. Generators
    // and coroutines push their own item while they run, and the bottom of the
    // list is always tstate->exc_state. If exc_info points at tstate->exc_state
    // we record NULL instead: that address is inside the shared thread state,
    // load_task_state() recomputes it.
    dst->exc_info = tstate->exc_info == &tstate->exc_state ? NULL : tstate->exc_info;
    dst->exc_state = tstate->exc_state;
    dst->current_exception = tstate->current_exception;
    dst->py_recursion_remaining = tstate->py_recursion_remaining;
    dst->tracing = tstate->tracing;
    dst->what_event = tstate->what_event;
    dst->delete_later = tstate->delete_later;
    dst->datastack_chunk = tstate->datastack_chunk;
    dst->datastack_top = tstate->datastack_top;
    dst->datastack_limit = tstate->datastack_limit;
    dst->current_executor = tstate->current_executor;
    dst->asyncio_running_task = swap_asyncio_running_task(tstate, NULL);
}

// Move the per-task fields from `src` into the thread state. `src` is zeroed.
static void
load_task_state(PyThreadState* tstate, TaskState* src)
{
    tstate->context = src->context;
    // invalidates the contextvars cache, which would otherwise stay valid
    // across the switch
    tstate->context_ver++;
    tstate->current_frame = src->current_frame;
    tstate->exc_state = src->exc_state;
    tstate->exc_info = src->exc_info ? src->exc_info : &tstate->exc_state;
    tstate->current_exception = src->current_exception;
    tstate->py_recursion_remaining = src->py_recursion_remaining;
    tstate->tracing = src->tracing;
    tstate->what_event = src->what_event;
    tstate->delete_later = src->delete_later;
    tstate->datastack_chunk = src->datastack_chunk;
    tstate->datastack_top = src->datastack_top;
    tstate->datastack_limit = src->datastack_limit;
    tstate->current_executor = src->current_executor;
    PyObject* old = swap_asyncio_running_task(tstate, src->asyncio_running_task);
    (void)old;  // (NULL: save_task_state took it off)
    memset(src, 0, sizeof(*src));
}

// Set up the thread state for a brand new task, right after
// save_task_state(): the fields inherited from the caller are still on the
// thread state, everything else becomes a blank slate. Steals a reference to
// `context`.
static void
init_fresh_task(PyThreadState* tstate, PyObject* context)
{
    tstate->context = context;
    tstate->context_ver++;
    tstate->current_frame = NULL;
    memset(&tstate->exc_state, 0, sizeof(tstate->exc_state));
    tstate->exc_info = &tstate->exc_state;
    tstate->current_exception = NULL;
    // py_recursion_remaining, tracing, what_event: inherited from the caller
    tstate->delete_later = NULL;
    tstate->datastack_chunk = NULL;
    tstate->datastack_top = NULL;
    tstate->datastack_limit = NULL;
    tstate->current_executor = NULL;
    // (asyncio_running_task: set to NULL by save_task_state)
}

// Release everything the finished task installed on the thread state owns.
// Followed by load_task_state().
static void
cleanup_task(PyThreadState* tstate)
{
    // the task's Python code has returned: the frame chain is back to empty
    Py_CLEAR(tstate->context);
    Py_CLEAR(tstate->exc_state.exc_value);
    // (pyjs_call_promising moved a pending exception out before; NULL here)
    Py_CLEAR(tstate->current_exception);
    free_datastack(tstate->datastack_chunk);
    tstate->datastack_chunk = NULL;
    tstate->datastack_top = NULL;
    tstate->datastack_limit = NULL;
    Py_XDECREF(swap_asyncio_running_task(tstate, NULL));
}

// ---------------------------------------------------------------------------
// the entry points
// ---------------------------------------------------------------------------

// Start a new task (pyjs_call_promising, before the Python call). It runs on
// the same thread state as its caller but with a frame chain, exception stack
// and contextvars context of its own: a COPY of the caller's context, so
// contextvar changes made by the task stay local to it (like an asyncio task).
// The caller's state is stashed in `outer`. 0, or -1 with an exception set.
int
pyjs_enter_promising_task(void)
{
    if (in_task)
    {
        // A promising call is only started from the event loop level (see
        // callPythonPromising), so normally no task is running here. It
        // does happen after a task crashed (a wasm trap: its state was
        // never taken off the thread state), and the caller must cope:
        // pyjs_call_promising reports RC_NOT_ENTERED.
        PyErr_SetString(PyExc_SystemError,
                        "pyjs: cannot enter a promising task from inside another running one");
        return -1;
    }
    PyObject* context = PyContext_CopyCurrent();
    if (context == NULL)
    {
        return -1;
    }
    PyThreadState* tstate = PyThreadState_Get();
    save_task_state(tstate, &outer);
    init_fresh_task(tstate, context);
    in_task = true;
    return 0;
}

// Finish the current task and put back the caller's state. A pending
// exception must have been moved out of the thread state before (see
// pyjs_call_promising).
void
pyjs_exit_promising_task(void)
{
    PyThreadState* tstate = PyThreadState_Get();
    cleanup_task(tstate);
    load_task_state(tstate, &outer);
    in_task = false;
}

// Suspend the current task (JS, right before run_sync suspends): move its
// state off the thread state into a heap allocated TaskState and restore the
// caller's state. The returned address is kept by the JS side and given back
// to pyjs_restore_task_state when the task resumes. 0 if not inside a task.
//
// With the task's frames off the thread state, a suspended task looks like
// Python code that is not running, which is what the GC and everything else
// walking current_frame expects. Its objects are kept alive by their
// reference counts (the frames on its own data stack hold them).
EMSCRIPTEN_KEEPALIVE TaskState*
pyjs_capture_task_state(void)
{
    if (!in_task)
    {
        return NULL;
    }
    TaskState* saved = malloc(sizeof(TaskState));
    if (saved == NULL)
    {
        return NULL;
    }
    PyThreadState* tstate = PyThreadState_Get();
    save_task_state(tstate, saved);
    load_task_state(tstate, &outer);
    in_task = false;
    return saved;
}

// Resume a suspended task (JS, right after run_sync's promise settled):
// stash the current state in `outer` and install the task's state. Frees
// `saved`.
EMSCRIPTEN_KEEPALIVE void
pyjs_restore_task_state(TaskState* saved)
{
    PyThreadState* tstate = PyThreadState_Get();
    save_task_state(tstate, &outer);
    load_task_state(tstate, saved);
    free(saved);
    in_task = true;
}
