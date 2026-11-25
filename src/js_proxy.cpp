// JSProxy: a Python object that stands for a JavaScript object.
//
// WHAT IT IS FOR. A JavaScript object (say `document`) cannot live inside
// Python. Instead Python gets a small object, the proxy, that remembers which
// JavaScript object it means and forwards everything done to it:
//
//     python                          what happens
//     ------------------------------  ---------------------------------------
//     doc.title                       js_proxy_getattro -> JS: obj["title"]
//     doc.title = "x"                 js_proxy_setattro -> JS: obj["title"] = "x"
//     f(1, 2)                         js_proxy_vectorcall -> JS: f(1, 2)
//     len(arr), arr[0], x in arr      js_proxy_len / _getitem / _contains
//     for x in arr                    js_proxy_iter / _next
//
// HOW THE FORWARDING WORKS. Each operation is exactly ONE call from wasm into
// JavaScript ("hop"), because hops are the expensive part:
//   1. the Python arguments are written into slots (to_slot; slot.hpp explains
//      what a slot is)
//   2. one of the EM_JS functions below is called. EM_JS is emscripten's way
//      of writing a JavaScript function inside a C++ file; each of them is a
//      one-liner forwarding to the real code in src/js/jsops.ts (`pyjsCore.xxx`)
//   3. JavaScript does the operation and writes the result into a result slot
//   4. back here the result slot becomes a Python object (from_slot)
// JavaScript never throws into wasm: an error comes back as return code (JsRc)
// with the thrown value in the result slot, and is raised here as a Python
// exception.
//
// A call, `f(1, "a")` in Python (the same as a diagram: docs/design.md):
//
//   Python          C++ (this file)              JavaScript (jsops.ts)
//   f(1, "a") ----> js_proxy_vectorcall
//                   to_slot(1), to_slot("a")
//                   pyjs_js_call(h, slots) ----> call(): decode the slots
//                                                f(1, "a")
//                                                encode(result) -> out slot
//                   rc = OK / ERROR <----------- (borrowed PyProxies destroyed)
//                   OK:    from_slot(out)
//                   ERROR: raise_from_slot(out)
//   result <------- (a value, or a JSProxy)
//
// This file also contains the two conversion functions to_slot / from_slot
// (the "implicit conversion" of values between the languages), because they
// need to know the proxy type.
#include "slot.hpp"

#include <emscripten.h>

#include <cstddef>
#include <cmath>
#include <cstdlib>
#include <cstring>
#include <vector>

// return codes of the JS operations
enum JsRc : int
{
    RC_OK = 0,
    RC_ERROR = 1,     // the result slot holds the thrown value
    RC_NO_ATTR = 2,
    RC_NO_INDEX = 3,
    RC_NO_KEY = 4,
    RC_STOP = 5,      // iterator exhausted
    RC_GENERIC = 6,   // no fast path for this object: use the generic operation
    RC_UNSUPPORTED = 7,  // the object cannot do this: a TypeError
};

// The operations Python can do on a JS object (through a JSProxy), besides
// the four frequent ones below.
//
// Every EM_JS function is one import of the wasm module, i.e. one way for
// the C++ code to call into JavaScript. The frequent operations get an
// import of their own (call, getattr, getindex, setattr: below), which keeps
// them as fast as possible. All others go through ONE import, `pyjs_js_op`,
// which gets the operation as a number (`JsOp`) and dispatches on it in
// JavaScript (`op` in src/js/jsops.ts). The numbers must match the enum
// `Op` there.
//
//   operation         Python code that triggers it        C++ function here
//   OP_GETITEM        proxy[key] (non-index keys)         js_proxy_getitem
//   OP_SETITEM        proxy[key] = value                  js_proxy_setitem
//   OP_DELITEM        del proxy[key]                      js_proxy_setitem
//   OP_LEN            len(proxy)                          js_proxy_len
//   OP_CONTAINS       value in proxy                      js_proxy_contains
//   OP_BOOL           bool(proxy), if proxy:              js_proxy_bool
//   OP_REPR           repr(proxy), str(proxy)             js_proxy_repr
//   OP_TYPEOF         proxy.typeof                        js_proxy_typeof
//   OP_ITER           iter(proxy), for x in proxy         js_proxy_iter
//   OP_NEXT           next(iterator)                      js_proxy_next
//   OP_SAME           proxy == other (same JS object)     js_proxy_richcompare
//   OP_GLOBAL         pyjs_core.global_this() / module()  js_global
//   OP_CREATE_PROXY   pyjs_core.create_proxy(obj)         create_proxy
//   OP_ID             hash(proxy), proxy.js_id            js_proxy_hash / _js_id
//
// All are tested: tests/test_pyjs.py, tests/test_proxy_types.py and the
// ported pyodide tests (tests/pyodide/test_pyodide_jsproxy.py).
enum JsOp : int
{
    OP_GETITEM = 0,
    OP_SETITEM = 1,
    OP_DELITEM = 2,
    OP_LEN = 3,
    OP_CONTAINS = 4,
    OP_BOOL = 5,
    OP_REPR = 6,
    OP_TYPEOF = 7,
    OP_ITER = 8,
    OP_NEXT = 9,
    OP_SAME = 10,
    OP_GLOBAL = 11,        // handle: 0 = globalThis, 1 = the emscripten Module
    OP_CREATE_PROXY = 12,  // a PyProxy for a Python object, as JSProxy
    OP_ID = 13,            // a number identifying the JS object
};

// call `fn` (handle) with `this` = self (handle or 0): `args` points to npos +
// nkw value slots followed by nkw name slots; construct: `new fn(...)`
EM_JS(int, pyjs_js_call, (int fn, int self, double args, int npos, int nkw, int construct, double out), {
    return pyjsCore.call(fn, self, args, npos, nkw, construct, out);
});

EM_JS(int, pyjs_js_getattr, (int h, int name, double out), {
    return pyjsCore.getattr(h, name, out);
});

// obj[index] of an Array / typed array (negative: from the end); RC_GENERIC
// for other objects
EM_JS(int, pyjs_js_getindex, (int h, double index, double out), {
    return pyjsCore.getindex(h, index, out);
});

// value: a slot, or 0 to delete the attribute
EM_JS(int, pyjs_js_setattr, (int h, int name, double value, double out), {
    return pyjsCore.setattr(h, name, value, out);
});

// handle of the JS string for an attribute name (utf8)
EM_JS(int, pyjs_js_name, (double ptr, int len), {
    return pyjsCore.name(ptr, len);
});

// release handles (0: none)
EM_JS(void, pyjs_js_free, (int h, int h2), {
    pyjsCore.free(h, h2);
});

EM_JS(int, pyjs_js_op, (int op, int h, double arg, double arg2, double out), {
    return pyjsCore.op(op, h, arg, arg2, out);
});

// The suspend point of pyjs.run_sync (JSPI): a wasm import that is wrapped in
// WebAssembly.Suspending when the browser supports JSPI. The wrapping happens
// here, in the JS emitted for this function, which runs before the wasm module
// is instantiated. Without JSPI the plain function stays in place; it is never
// called then (pyjs.can_run_sync() is False).
//
// Returns 0 (not suspended, error in `out`) or, after the suspension, a token
// for pyjs_js_resume. See jspiAwait / jspiResume in src/js/jsops.ts.
EM_JS(int, pyjs_js_await, (int promise, double out), {
    throw new Error("pyjs: run_sync without JSPI support");
}
if (typeof WebAssembly !== "undefined" && typeof WebAssembly.Suspending === "function") {
    // (no async function: a plain number result means "do not suspend")
    pyjs_js_await = new WebAssembly.Suspending(function (promise, out) {
        return pyjsCore.jspiAwait(promise, out);
    });
}
);

// Right after the resumption: the task's state back in place, the result of
// the promise into `out`.
EM_JS(int, pyjs_js_resume, (int token, double out), {
    return pyjsCore.jspiResume(token, out);
});

namespace pyjs
{
    // An "anonymous namespace" (a namespace without a name) makes everything
    // inside it private to this file: other .cpp files cannot see or call it,
    // and its names cannot clash with names elsewhere (C++'s version of
    // `static` for functions and globals). Only what slot.hpp declares (to_slot,
    // from_slot, js_proxy_new, ...) is defined outside of it and shared.
    namespace
    {
        // The memory of one proxy object.
        struct JsProxyObject
        {
            // PyObject_HEAD is a macro of CPython: it expands to the fields
            // every Python object starts with (its reference count and a
            // pointer to its type). Putting it first makes a JsProxyObject*
            // usable wherever CPython expects a PyObject*.
            PyObject_HEAD
            // Which JavaScript object this proxy stands for. JavaScript keeps
            // the objects Python refers to in a table; the handle is the
            // index into it (src/js/codec.ts, "handles"). The proxy owns the
            // handle: it frees it when it dies (js_proxy_dealloc).
            int32_t handle;
            // Only for functions that were fetched from an object, like
            // `f = obj.method`: the handle of that object, so that `f(...)`
            // can run the function as method of it (as JavaScript's `this`).
            // 0 for everything else. Owned and freed like `handle`.
            int32_t this_handle;
            // The C function Python calls for `proxy(...)`.
            //
            // "Vectorcall" is CPython's fast calling convention (PEP 590):
            // the arguments are passed as a plain C array of PyObject* (a
            // "vector") plus a count, instead of first packing them into a
            // new tuple (and the keyword arguments into a new dict), as the
            // classic `tp_call` does. For a call into JavaScript, where the
            // arguments are written into slots right away, the tuple would be
            // pure overhead. A type opts in with Py_TPFLAGS_HAVE_VECTORCALL
            // and tells CPython where in the object this function pointer is
            // (`__vectorcalloffset__`, see type_for). nullptr for proxies of
            // things that are not callable.
            vectorcallfunc vectorcall;
        };

        // The Python types of the proxies.
        //
        // What a Python object can do depends on its type: `len(x)` only
        // works if the type of x has a length function, and so on. JavaScript
        // objects differ in what they can do (an Array has a length and can
        // be iterated, a function can be called, a promise can be awaited),
        // and Python code tests for that (`callable(x)`, `hasattr(x,
        // "__len__")`, `iter(x)`).
        //
        // So there is not one proxy type but one per COMBINATION of abilities.
        // JavaScript reports the abilities of an object as bit flags (JsFlag
        // in slot.hpp); this array maps a flag combination to its type. The
        // types are created the first time they are needed (type_for). All of
        // them derive from the type for "no abilities" (index 0), which is
        // the `JSProxy` users see, so isinstance(x, JSProxy) holds for all.
        //
        // (One pointer per possible combination: 16384 of them, almost all
        // never used. That is 64 KiB of memory that starts out as zeros,
        // which costs nothing in the binary, and finding the type is a
        // single array access.)
        PyTypeObject* g_types[JS_FLAG_END] = {};

        // The Python functions / classes of the `pyjs` package this core
        // calls back into (raise a JS error, await a promise, ...): what they
        // are and why they exist is explained at `struct Hooks` in slot.hpp.
        // Filled by pyjs_core.set_hooks (src/module.cpp).
        Hooks g_hooks;

        // (the same memory, seen as proxy)
        inline JsProxyObject* as_proxy(PyObject* o)
        {
            return reinterpret_cast<JsProxyObject*>(o);
        }

        void js_proxy_dealloc(PyObject* self);

        // Is `o` a JSProxy? This runs for every argument of every call, so it
        // has to be cheap. All proxy types (and only they) use
        // js_proxy_dealloc to destroy their objects: comparing that one
        // function pointer answers the question without walking the type
        // hierarchy.
        inline bool is_js_proxy(PyObject* o)
        {
            return Py_TYPE(o)->tp_dealloc == js_proxy_dealloc;
        }

        // ------------------------------------------------------------------
        // The cache of attribute names.
        //
        // The situation: Python code runs `obj.title`, where `obj` is a
        // JSProxy. We are in C++ (Python called js_proxy_getattro), and have
        // to make JavaScript do `obj["title"]`. In JavaScript a property name
        // is a JavaScript string; Python only has the Python string "title".
        // So the name has to become a JavaScript string on the JS side, which
        // means copying its bytes over and decoding them there.
        //
        // Doing that on every access would cost more than the access itself.
        // But Python code uses the SAME string object every time a line like
        // `obj.title` runs (names in code are created once). So the
        // JavaScript string is created once, kept in JavaScript's table of
        // objects (a handle, see codec.ts), and found again by the address of
        // the Python string.
        //
        // The cache is a plain array ("direct mapped"): the address of the
        // string, cut down to a number below N_NAMES, is the index. Two
        // different strings can land on the same index; then the newer one
        // simply replaces the older one (which is recreated when needed
        // again). No searching, no bookkeeping.
        //
        // Each entry holds a reference to its Python string. That keeps the
        // string alive, which is what makes comparing addresses safe: as
        // long as the entry exists no other string can get that address.
        // ------------------------------------------------------------------
        struct NameEntry
        {
            PyObject* key;
            int handle;
        };
        constexpr std::size_t N_NAMES = 1024;
        NameEntry g_names[N_NAMES] = {};

        // handle of the JS string of an attribute name, 0 with an exception set
        inline int name_handle(PyObject* name)
        {
            NameEntry& entry = g_names[(reinterpret_cast<std::uintptr_t>(name) >> 3) % N_NAMES];
            if (entry.key == name)
            {
                return entry.handle;
            }
            Py_ssize_t len;
            const char* utf8 = PyUnicode_AsUTF8AndSize(name, &len);
            if (utf8 == nullptr)
            {
                return 0;
            }
            const int handle = pyjs_js_name(ptr_to_num(utf8), static_cast<int>(len));
            if (entry.key != nullptr)
            {
                pyjs_js_free(entry.handle, 0);
                Py_DECREF(entry.key);
            }
            entry.key = Py_NewRef(name);
            entry.handle = handle;
            return handle;
        }

    }  // (end of the file-local part; raise_from_slot is also used by deep.cpp)

    // Raise the Python exception for an error slot (tag T_ERROR): what
    // JavaScript reports when an operation threw. Two cases:
    //
    //   aux == 0   Yes, really a Python error, passing through. Python
    //              called a JS function, which called a Python function,
    //              which raised:
    //                  Python  ->  JS  ->  Python (raises ValueError)
    //              On its way back the ValueError had to cross JavaScript,
    //              where it was thrown as a JS Error (a "PythonError",
    //              holding the address of the exception object). Now it
    //              arrives back in Python: `num` is that address, and the
    //              very same ValueError is raised again (not a JSException
    //              around it), so `except ValueError` in the outer Python
    //              code works.
    //   aux != 0   A JavaScript value was thrown; aux is a handle to it. It
    //              is wrapped in a JSProxy and handed to the hook
    //              (pyjs.error_handling.error_to_py_and_raise), which raises
    //              a JSException for it (see error_to_py there for the
    //              whole path).
    void raise_from_slot(Slot* slot)
    {
        if (slot->aux == 0)
        {
            PyErr_SetRaisedException(Py_NewRef(num_to_ptr<PyObject>(slot->num)));
            return;
        }
        PyObject* error = js_proxy_new(slot->aux, slot->i.a, 0);
        if (error == nullptr)
        {
            return;
        }
        if (g_hooks.raise_js_error == nullptr)
        {
            // (only before the python package pyjs is imported)
            PyErr_SetObject(PyExc_RuntimeError, error);
        }
        else
        {
            // the hook is expected to raise: then the call "fails" and the
            // exception it raised is the one we want
            PyObject* ret = PyObject_CallOneArg(g_hooks.raise_js_error, error);
            if (ret != nullptr)
            {
                Py_DECREF(ret);
                PyErr_SetString(PyExc_RuntimeError, "pyjs: the error hook did not raise");
            }
        }
        Py_DECREF(error);
    }

    // (file-local again, see the first anonymous namespace above: the
    // functions below are only used in this file. The namespace is closed
    // in between because raise_from_slot above is shared with deep.cpp.)
    namespace
    {
        // the Python result of a JS operation: its value, or the exception of `rc`
        PyObject* result(int rc, Slot* out, PyObject* key = nullptr)
        {
            switch (rc)
            {
                case RC_OK:
                    return from_slot(out);
                case RC_ERROR:
                    raise_from_slot(out);
                    return nullptr;
                case RC_NO_ATTR:
                    PyErr_SetObject(PyExc_AttributeError, key);
                    return nullptr;
                case RC_NO_INDEX:
                    PyErr_SetString(PyExc_IndexError, "index out of range");
                    return nullptr;
                case RC_NO_KEY:
                    PyErr_SetObject(PyExc_KeyError, key);
                    return nullptr;
                case RC_UNSUPPORTED:
                    PyErr_SetString(PyExc_TypeError, "this JavaScript object does not support the operation");
                    return nullptr;
                default:
                    PyErr_SetNone(PyExc_StopIteration);
                    return nullptr;
            }
        }

        // like result(), for operations without a value: 0 or -1
        int status(int rc, Slot* out, PyObject* key = nullptr)
        {
            if (rc == RC_OK)
            {
                return 0;
            }
            PyObject* ret = result(rc, out, key);
            Py_XDECREF(ret);
            return -1;
        }

        // give back what the slots own (arguments that never reached JS)
        void release_slots(Slot* slots, Py_ssize_t n)
        {
            for (Py_ssize_t i = 0; i < n; ++i)
            {
                if (slots[i].tag == T_PY)
                {
                    Py_DECREF(num_to_ptr<PyObject>(slots[i].num));
                }
                else if (slots[i].tag & T_OWNED)
                {
                    std::free(num_to_ptr<char>(slots[i].num));
                }
            }
        }

        // ------------------------------------------------------------------
        // the slots of the types
        // ------------------------------------------------------------------
        void js_proxy_dealloc(PyObject* self)
        {
            PyTypeObject* type = Py_TYPE(self);
            pyjs_js_free(as_proxy(self)->handle, as_proxy(self)->this_handle);
            type->tp_free(self);
            Py_DECREF(type);
        }

        // proxy.name
        //
        // Where we are: Python code (running in wasm) evaluates `proxy.name`,
        // where `proxy` is a JSProxy, i.e. a Python object standing for a
        // JavaScript object. CPython calls this function (the type's
        // tp_getattro slot) to get the attribute. We are still in C++; the
        // JavaScript object itself is only reached through pyjs_js_getattr.
        //
        // Two places are searched, in this order:
        //   1. the Python type of the proxy. That is where the methods of the
        //      proxy itself live (to_py, new, typeof, js_id, __len__, ...).
        //   2. the JavaScript object: obj["name"].
        // So a JavaScript property with the same name as a proxy method is
        // hidden; it can still be reached with proxy["name"].
        //
        // _PyType_Lookup looks a name up in a type and its bases without
        // raising anything when it is missing (and CPython caches it), which
        // matters because "missing" is the normal case here: almost every
        // attribute access is meant for the JavaScript object.
        PyObject* js_proxy_getattro(PyObject* self, PyObject* name)
        {
            PyObject* descr = _PyType_Lookup(Py_TYPE(self), name);
            if (descr != nullptr)
            {
                // Found in the type. What is stored there is usually not the
                // final value but a "descriptor": e.g. a function, which has
                // to be turned into a method bound to this proxy. Its type
                // provides the function doing that (tp_descr_get); plain
                // values have none and are returned as they are.
                descrgetfunc get = Py_TYPE(descr)->tp_descr_get;
                if (get != nullptr)
                {
                    return get(descr, self, reinterpret_cast<PyObject*>(Py_TYPE(self)));
                }
                return Py_NewRef(descr);
            }
            const int name_h = name_handle(name);
            if (name_h == 0)
            {
                return nullptr;
            }
            Slot out;
            const int rc = pyjs_js_getattr(as_proxy(self)->handle, name_h, ptr_to_num(&out));
            return result(rc, &out, name);
        }

        // `proxy.name = value` and `del proxy.name`: set or delete a property
        // of the JS object.
        //
        // Why one function for both: that is how CPython defines it. A type
        // has ONE slot for writing attributes (tp_setattro), and CPython calls
        // it with the new value for `proxy.name = value` and with
        // value = nullptr for `del proxy.name`. (The same for items:
        // `obj[k] = v` and `del obj[k]` both call mp_ass_subscript, see
        // js_proxy_setitem.) The JS side gets the same convention: a value
        // slot, or 0 for "delete" (`delete obj[name]`).
        int js_proxy_setattro(PyObject* self, PyObject* name, PyObject* value)
        {
            const int name_h = name_handle(name);
            if (name_h == 0)
            {
                return -1;
            }
            Slot in, out;
            if (value != nullptr && !to_slot(value, &in))
            {
                return -1;
            }
            const int rc = pyjs_js_setattr(
                as_proxy(self)->handle, name_h, value != nullptr ? ptr_to_num(&in) : 0.0, ptr_to_num(&out));
            return status(rc, &out, name);
        }

        // proxy(*args, **kwargs), or with construct = 1: `new proxy(...)`.
        //
        // How Python hands over the arguments (CPython's "vectorcall"
        // convention): `args` is an array with first the `npos` positional
        // arguments and then the VALUES of the keyword arguments; `kwnames`
        // is a tuple with the NAMES of the keyword arguments (or nullptr).
        // For f(1, 2, a=3, b=4):   args = [1, 2, 3, 4]   kwnames = ("a", "b")
        //
        // What JavaScript gets: one array of slots,
        //
        //     [ positional values | keyword values | keyword names ]
        //       npos                nkw              nkw
        //
        // (JavaScript turns the keyword part into one trailing object
        // {a: 3, b: 4}, as JavaScript functions take "options" that way.)
        PyObject* call_js(PyObject* self, PyObject* const* args, Py_ssize_t npos, PyObject* kwnames, int construct)
        {
            const Py_ssize_t nkw = kwnames != nullptr ? PyTuple_GET_SIZE(kwnames) : 0;
            const Py_ssize_t nvalues = npos + nkw;
            // The slots live on the C stack for the common case of few
            // arguments (no allocation); only a long argument list uses the
            // heap.
            Slot small[8];
            Slot* slots = small;
            if (nvalues + nkw > 8)
            {
                slots = static_cast<Slot*>(PyMem_Malloc((nvalues + nkw) * sizeof(Slot)));
                if (slots == nullptr)
                {
                    PyErr_NoMemory();
                    return nullptr;
                }
            }
            PyObject* ret = nullptr;
            // `n` counts the slots written so far. Converting can fail (then
            // a Python exception is set and the loops stop early).
            Py_ssize_t n = 0;
            // the values: positional and keyword
            for (; n < nvalues; ++n)
            {
                if (!to_slot(args[n], &slots[n]))
                {
                    break;
                }
            }
            // the keyword names (the condition `n == nvalues + i` is false as
            // soon as anything before failed)
            for (Py_ssize_t i = 0; n == nvalues + i && i < nkw; ++i)
            {
                n += to_slot(PyTuple_GET_ITEM(kwnames, i), &slots[nvalues + i]) ? 1 : 0;
            }
            if (n != nvalues + nkw)
            {
                // Failed half way: JavaScript is not called. Some of the
                // slots written so far own something (a reference to a Python
                // object, a buffer) that JavaScript would have taken over:
                // give it back.
                release_slots(slots, n);
            }
            else
            {
                Slot out;
                const int rc = pyjs_js_call(as_proxy(self)->handle,
                                            as_proxy(self)->this_handle,
                                            ptr_to_num(slots),
                                            static_cast<int>(npos),
                                            static_cast<int>(nkw),
                                            construct,
                                            ptr_to_num(&out));
                ret = result(rc, &out);
            }
            if (slots != small)
            {
                PyMem_Free(slots);
            }
            return ret;
        }

        PyObject* js_proxy_vectorcall(PyObject* self, PyObject* const* args, size_t nargsf, PyObject* kwnames)
        {
            return call_js(self, args, PyVectorcall_NARGS(nargsf), kwnames, 0);
        }

        // JSProxy.new(*args, **kwargs): `new self(...)`
        PyObject* js_proxy_construct(PyObject* self, PyObject* const* args, Py_ssize_t nargs, PyObject* kwnames)
        {
            return call_js(self, args, nargs, kwnames, 1);
        }

        // Run one of the "rarely used" operations (JsOp, see the table at the
        // top of this file) on the JS object of `self`.
        //
        // Why it exists: all those operations look the same from here. They
        // take up to two Python values (`arg`: e.g. the key of proxy[key],
        // `arg2`: e.g. the value of proxy[key] = value; nullptr if unused),
        // convert them to slots, make ONE call into JavaScript (the shared
        // import pyjs_js_op, dispatching on `op`) and get a return code (JsRc)
        // plus the result in `out`. This function does the part that is the
        // same for all: the slots and the call. Each user (js_proxy_len,
        // js_proxy_contains, js_proxy_repr, ...) then only interprets `out`.
        //
        // Returns the JsRc of the JavaScript side, or -1 if converting an
        // argument failed (Python exception set; JavaScript was not called).
        int op(JsOp op, PyObject* self, PyObject* arg, PyObject* arg2, Slot* out)
        {
            Slot in, in2;
            if (arg != nullptr && !to_slot(arg, &in))
            {
                return -1;
            }
            if (arg2 != nullptr && !to_slot(arg2, &in2))
            {
                release_slots(&in, arg != nullptr ? 1 : 0);
                return -1;
            }
            return pyjs_js_op(op,
                              as_proxy(self)->handle,
                              arg != nullptr ? ptr_to_num(&in) : 0.0,
                              arg2 != nullptr ? ptr_to_num(&in2) : 0.0,
                              ptr_to_num(out));
        }

        // Slices (`proxy[1:3]`, `proxy[::2] = ...`, `del proxy[:2]`) are not
        // done here but by Python functions named _getslice / _setslice /
        // _delslice, which the proxy types of arrays and typed arrays
        // inherit (pyjs/_proxy_types.py): a slice is several JavaScript
        // operations, which is much shorter to write in Python.
        //
        // Returns that function for the type of `self` (a borrowed
        // reference), or nullptr with a TypeError set if the JavaScript
        // object is nothing that can be sliced.
        PyObject* slice_function(PyObject* self, const char* name)
        {
            PyObject* key = PyUnicode_InternFromString(name);
            if (key == nullptr)
            {
                return nullptr;
            }
            PyObject* function = _PyType_Lookup(Py_TYPE(self), key);
            Py_DECREF(key);
            if (function == nullptr)
            {
                PyErr_SetString(PyExc_TypeError, "this JavaScript object does not support slices");
            }
            return function;
        }

        Py_ssize_t js_proxy_len(PyObject* self);

        // A negative index counts from the end, which needs the length. When
        // such an index was out of range (rc RC_NO_INDEX), the reason may be
        // a length that is no length (JavaScript objects can claim a negative
        // or a huge one): then raise what len() raises for it, not the
        // IndexError. False with that exception set.
        bool negative_index_check(PyObject* self, PyObject* key, int rc)
        {
            if (rc != RC_NO_INDEX || !PyLong_Check(key))
            {
                return true;
            }
            // key < 0 (False is the int 0; an int of any size compares)
            const int negative = PyObject_RichCompareBool(key, Py_False, Py_LT);
            return negative != 1 || js_proxy_len(self) >= 0;
        }

        PyObject* js_proxy_getitem(PyObject* self, PyObject* key)
        {
            if (PySlice_Check(key))
            {
                PyObject* function = slice_function(self, "_getslice");
                return function != nullptr ? PyObject_CallFunctionObjArgs(function, self, key, nullptr) : nullptr;
            }
            Slot out;
            if (PyLong_CheckExact(key))
            {
                // sequence[int] without converting the key
                const double index = PyLong_AsDouble(key);
                if (index == -1.0 && PyErr_Occurred())
                {
                    return nullptr;
                }
                const int rc = pyjs_js_getindex(as_proxy(self)->handle, index, ptr_to_num(&out));
                if (rc != RC_GENERIC)
                {
                    return negative_index_check(self, key, rc) ? result(rc, &out, key) : nullptr;
                }
            }
            const int rc = op(OP_GETITEM, self, key, nullptr, &out);
            return rc < 0 ? nullptr : negative_index_check(self, key, rc) ? result(rc, &out, key) : nullptr;
        }

        // obj[key] = value, or del obj[key] (value: nullptr)
        int js_proxy_setitem(PyObject* self, PyObject* key, PyObject* value)
        {
            if (PySlice_Check(key))
            {
                // (see slice_function)
                PyObject* function = slice_function(self, value != nullptr ? "_setslice" : "_delslice");
                PyObject* ret = function != nullptr ? PyObject_CallFunctionObjArgs(function, self, key, value, nullptr)
                                                    : nullptr;
                Py_XDECREF(ret);
                return ret != nullptr ? 0 : -1;
            }
            Slot out;
            const int rc = op(value != nullptr ? OP_SETITEM : OP_DELITEM, self, key, value, &out);
            return rc < 0 ? -1 : status(rc, &out, key);
        }

        Py_ssize_t js_proxy_len(PyObject* self)
        {
            Slot out;
            const int rc = op(OP_LEN, self, nullptr, nullptr, &out);
            if (rc < 0 || status(rc, &out) < 0)
            {
                return -1;
            }
            // JavaScript can say anything here (`{length: -1}`,
            // `{length: 1e20}`): python requires 0 <= len <= the largest
            // Py_ssize_t. (A negative return value means "error" to
            // python, so returning one without an exception set must not
            // happen.)
            const double length = out.num;
            if (!(length >= 0))
            {
                PyErr_SetString(PyExc_ValueError, "__len__() should return >= 0");
                return -1;
            }
            // (compared with 2^31 / 2^63 itself: PY_SSIZE_T_MAX = 2^63 - 1
            // has no exact double and rounds UP to 2^63, so `length >
            // PY_SSIZE_T_MAX` would let 2^63 through)
            const double limit = std::ldexp(1.0, static_cast<int>(sizeof(Py_ssize_t) * 8 - 1));
            if (length >= limit)
            {
                PyErr_SetString(PyExc_OverflowError, "the length of the JavaScript object does not fit a Python int index");
                return -1;
            }
            return static_cast<Py_ssize_t>(length);
        }

        int js_proxy_contains(PyObject* self, PyObject* value)
        {
            Slot out;
            const int rc = op(OP_CONTAINS, self, value, nullptr, &out);
            if (rc < 0 || status(rc, &out) < 0)
            {
                return -1;
            }
            return out.tag == T_TRUE ? 1 : 0;
        }

        int js_proxy_bool(PyObject* self)
        {
            Slot out;
            const int rc = op(OP_BOOL, self, nullptr, nullptr, &out);
            if (rc < 0 || status(rc, &out) < 0)
            {
                return -1;
            }
            return out.tag == T_TRUE ? 1 : 0;
        }

        PyObject* js_proxy_repr(PyObject* self)
        {
            Slot out;
            const int rc = op(OP_REPR, self, nullptr, nullptr, &out);
            return rc < 0 ? nullptr : result(rc, &out);
        }

        PyObject* js_proxy_iter(PyObject* self)
        {
            Slot out;
            const int rc = op(OP_ITER, self, nullptr, nullptr, &out);
            return rc < 0 ? nullptr : result(rc, &out);
        }

        PyObject* js_proxy_next(PyObject* self)
        {
            Slot out;
            const int rc = op(OP_NEXT, self, nullptr, nullptr, &out);
            if (rc == RC_STOP)
            {
                // tp_iternext: nullptr without exception = exhausted
                return nullptr;
            }
            return rc < 0 ? nullptr : result(rc, &out);
        }

        // == / != : the same JS object (===)
        PyObject* js_proxy_richcompare(PyObject* self, PyObject* other, int cmp)
        {
            if ((cmp != Py_EQ && cmp != Py_NE) || !is_js_proxy(other))
            {
                Py_RETURN_NOTIMPLEMENTED;
            }
            Slot out;
            const int rc = op(OP_SAME, self, other, nullptr, &out);
            if (rc < 0 || status(rc, &out) < 0)
            {
                return nullptr;
            }
            return PyBool_FromLong((out.tag == T_TRUE) == (cmp == Py_EQ));
        }

        // hash(proxy): by identity of the JS object, so that two proxies of
        // the same object (which compare equal) have the same hash. Needed
        // wherever proxies are dict keys or set members, e.g.
        // asyncio.gather(js_promise, ...) keeps its arguments in a dict.
        Py_hash_t js_proxy_hash(PyObject* self)
        {
            Slot out;
            const int rc = op(OP_ID, self, nullptr, nullptr, &out);
            if (rc < 0 || status(rc, &out) < 0)
            {
                return -1;
            }
            // (-1 is reserved: it means "error")
            const Py_hash_t hash = static_cast<Py_hash_t>(out.num);
            return hash == -1 ? -2 : hash;
        }

        PyObject* js_proxy_await(PyObject* self)
        {
            if (g_hooks.await_js == nullptr)
            {
                PyErr_SetString(PyExc_RuntimeError, "pyjs: awaiting JS objects is not set up");
                return nullptr;
            }
            return PyObject_CallOneArg(g_hooks.await_js, self);
        }

        // property typeof
        PyObject* js_proxy_typeof(PyObject* self, void*)
        {
            Slot out;
            const int rc = op(OP_TYPEOF, self, nullptr, nullptr, &out);
            return rc < 0 ? nullptr : result(rc, &out);
        }

        // property js_id: equal for two proxies iff they are the same JS object
        PyObject* js_proxy_js_id(PyObject* self, void*)
        {
            Slot out;
            const int rc = op(OP_ID, self, nullptr, nullptr, &out);
            return rc < 0 ? nullptr : result(rc, &out);
        }

        // JSProxy(obj): what `obj` is on the JS side, as seen from Python: the
        // object itself if it converts to a JS primitive, a proxy of a JS
        // object as is, and for any other Python object a JSProxy of its PyProxy
        PyObject* js_proxy_tp_new(PyTypeObject*, PyObject* args, PyObject* kwargs)
        {
            PyObject* obj;
            if (kwargs != nullptr && PyDict_GET_SIZE(kwargs) != 0)
            {
                PyErr_SetString(PyExc_TypeError, "JSProxy() takes no keyword arguments");
                return nullptr;
            }
            if (!PyArg_ParseTuple(args, "O:JSProxy", &obj))
            {
                return nullptr;
            }
            return create_proxy(obj, false, false);
        }

        // proxy.to_py(*, depth=-1, default_converter=None): a deep copy of
        // the JavaScript value as Python objects.
        //
        // A C function directly on the type (not a Python function calling
        // into C), because the call overhead is a visible part of converting
        // small values. The arguments arrive the "fastcall" way: `args` holds
        // the `nargs` positional arguments followed by the values of the
        // keyword arguments, `kwnames` is a tuple with their names.
        PyObject* js_proxy_to_py(PyObject* self, PyObject* const* args, Py_ssize_t nargs, PyObject* kwnames)
        {
            if (nargs != 0)
            {
                PyErr_SetString(PyExc_TypeError, "to_py() takes keyword arguments only (depth, default_converter)");
                return nullptr;
            }
            int depth = -1;
            PyObject* converter = nullptr;
            const Py_ssize_t nkw = kwnames != nullptr ? PyTuple_GET_SIZE(kwnames) : 0;
            for (Py_ssize_t i = 0; i < nkw; ++i)
            {
                PyObject* name = PyTuple_GET_ITEM(kwnames, i);
                PyObject* value = args[i];
                if (PyUnicode_CompareWithASCIIString(name, "depth") == 0)
                {
                    depth = static_cast<int>(PyLong_AsLong(value));
                    if (depth == -1 && PyErr_Occurred())
                    {
                        return nullptr;
                    }
                }
                else if (PyUnicode_CompareWithASCIIString(name, "default_converter") == 0)
                {
                    converter = value != Py_None ? value : nullptr;
                }
                else
                {
                    PyErr_Format(PyExc_TypeError, "to_py() got an unexpected keyword argument '%U'", name);
                    return nullptr;
                }
            }
            if (converter == nullptr)
            {
                // the normal case: the whole structure in one hop (deep.cpp)
                return deep_to_py(self, depth);
            }
            // A converter function has to be asked about individual objects:
            // that is done step by step by Python code (pyjs/convert.py).
            if (g_hooks.to_py_with_converter == nullptr)
            {
                PyErr_SetString(PyExc_RuntimeError, "pyjs: to_py with a converter is not set up");
                return nullptr;
            }
            return PyObject_CallFunction(g_hooks.to_py_with_converter, "OiO", self, depth, converter);
        }

        // methods of every proxy
        PyMethodDef g_methods[] = {
            { "to_py", reinterpret_cast<PyCFunction>(reinterpret_cast<void (*)()>(js_proxy_to_py)),
              METH_FASTCALL | METH_KEYWORDS,
              "to_py(*, depth=-1, default_converter=None)\n\n"
              "A deep copy of the JavaScript value as Python objects: Array -> list, Map and plain\n"
              "Object -> dict, Set -> set, typed array / ArrayBuffer -> memoryview. See pyjs.to_py." },
            { nullptr, nullptr, 0, nullptr },
        };

        // methods of proxies of functions / classes
        PyMethodDef g_callable_methods[] = {
            { "new", reinterpret_cast<PyCFunction>(reinterpret_cast<void (*)()>(js_proxy_construct)),
              METH_FASTCALL | METH_KEYWORDS, "new self(*args, **kwargs)" },
            { nullptr, nullptr, 0, nullptr },
        };

        PyGetSetDef g_getset[] = {
            { "typeof", js_proxy_typeof, nullptr, "the JavaScript `typeof` of the object", nullptr },
            { "js_id", js_proxy_js_id, nullptr, "an int, equal for two proxies iff they are the same object", nullptr },
            { nullptr, nullptr, nullptr, nullptr, nullptr },
        };

        PyMemberDef g_callable_members[] = {
            { "__vectorcalloffset__", Py_T_PYSSIZET, offsetof(JsProxyObject, vectorcall), Py_READONLY, nullptr },
            { nullptr, 0, 0, 0, nullptr },
        };

        // The Python type for proxies of JavaScript objects with the
        // abilities `flags` (see g_types). Created on first use and kept.
        //
        // A type is described to CPython as a list of "slots": pairs of (which
        // operation, the C function implementing it). E.g. {Py_mp_length,
        // js_proxy_len} means "len(x) calls js_proxy_len". (These type slots
        // have nothing to do with the value slots of slot.hpp.)
        //   - The base type (flags 0) gets everything that works for every
        //     JavaScript object: attribute access, obj[key], ==, hash, repr.
        //   - A type for some abilities derives from the base type and only
        //     adds the operations for those abilities.
        PyTypeObject* type_for(int flags)
        {
            if (g_types[flags] != nullptr)
            {
                return g_types[flags];
            }
            // (dealloc in every type: a heap type without one gets a generic
            // dealloc, and is_js_proxy recognizes the proxies by it)
            std::vector<PyType_Slot> slots = {
                { Py_tp_dealloc, reinterpret_cast<void*>(js_proxy_dealloc) },
            };
            unsigned int type_flags = Py_TPFLAGS_DEFAULT;
            if (flags == 0)
            {
                // the base: what every JS object can do
                type_flags |= Py_TPFLAGS_BASETYPE;
                slots = {
                    { Py_tp_dealloc, reinterpret_cast<void*>(js_proxy_dealloc) },
                    { Py_tp_new, reinterpret_cast<void*>(js_proxy_tp_new) },
                    { Py_tp_getattro, reinterpret_cast<void*>(js_proxy_getattro) },
                    { Py_tp_setattro, reinterpret_cast<void*>(js_proxy_setattro) },
                    { Py_tp_repr, reinterpret_cast<void*>(js_proxy_repr) },
                    { Py_tp_richcompare, reinterpret_cast<void*>(js_proxy_richcompare) },
                    { Py_tp_hash, reinterpret_cast<void*>(js_proxy_hash) },
                    { Py_nb_bool, reinterpret_cast<void*>(js_proxy_bool) },
                    { Py_tp_getset, g_getset },
                    { Py_tp_methods, g_methods },
                };
            }
            if (flags & JS_CALLABLE)
            {
                type_flags |= Py_TPFLAGS_HAVE_VECTORCALL;
                slots.push_back({ Py_tp_call, reinterpret_cast<void*>(PyVectorcall_Call) });
                slots.push_back({ Py_tp_members, g_callable_members });
                slots.push_back({ Py_tp_methods, g_callable_methods });
            }
            if (flags & JS_LENGTH)
            {
                slots.push_back({ Py_mp_length, reinterpret_cast<void*>(js_proxy_len) });
            }
            // obj[key] only for objects that are containers (arrays, typed
            // arrays, things with get() / set() like a Map). For any other
            // object Python reports "not subscriptable", as pyodide does: the
            // properties of a JavaScript object are its attributes (obj.name).
            if (flags & JS_GETITEM)
            {
                slots.push_back({ Py_mp_subscript, reinterpret_cast<void*>(js_proxy_getitem) });
            }
            if (flags & JS_SETITEM)
            {
                // (one function for `obj[key] = value` and `del obj[key]`)
                slots.push_back({ Py_mp_ass_subscript, reinterpret_cast<void*>(js_proxy_setitem) });
            }
            if (flags & JS_CONTAINS)
            {
                slots.push_back({ Py_sq_contains, reinterpret_cast<void*>(js_proxy_contains) });
            }
            // (Not for map-likes: JavaScript iterates a Map as [key, value]
            // pairs, but a Python mapping iterates its keys. Their __iter__
            // comes from the Python class JSMap, see below.)
            const bool iterable = (flags & JS_ITERABLE) && !(flags & JS_MAP);
            if (iterable)
            {
                slots.push_back({ Py_tp_iter, reinterpret_cast<void*>(js_proxy_iter) });
            }
            if (flags & JS_ITERATOR)
            {
                slots.push_back({ Py_tp_iternext, reinterpret_cast<void*>(js_proxy_next) });
                if (!iterable)
                {
                    slots.push_back({ Py_tp_iter, reinterpret_cast<void*>(PyObject_SelfIter) });
                }
            }
            if (flags & JS_AWAITABLE)
            {
                slots.push_back({ Py_am_await, reinterpret_cast<void*>(js_proxy_await) });
            }
            slots.push_back({ 0, nullptr });

            PyType_Spec spec = { "pyjs_core.JSProxy", sizeof(JsProxyObject), 0, type_flags, slots.data() };
            if (flags == 0)
            {
                g_types[0] = reinterpret_cast<PyTypeObject*>(PyType_FromSpec(&spec));
                return g_types[0];
            }
            // The base classes: (JSProxy, mixin classes...).
            //
            // The operations above are C functions. Some abilities come with
            // many more methods (an array has append / pop / insert / ...,
            // a map has keys / items / ...). Those are written in Python, as
            // small classes without data ("mixins", pyjs/_proxy_types.py).
            // The hook tells which of them belong to these flags, and the
            // type inherits from them: their methods, including special ones
            // like __aiter__, then work on the proxy like on any Python
            // object. Operations defined above win over inherited ones.
            PyObject* base = reinterpret_cast<PyObject*>(type_for(0));
            if (base == nullptr)
            {
                return nullptr;
            }
            // (no hook: only before the python package pyjs is imported)
            PyObject* mixins = g_hooks.proxy_mixins != nullptr ? PyObject_CallFunction(g_hooks.proxy_mixins, "i", flags)
                                                               : PyTuple_New(0);
            PyObject* first = PyTuple_Pack(1, base);
            PyObject* bases = mixins != nullptr && first != nullptr ? PySequence_Concat(first, mixins) : nullptr;
            Py_XDECREF(mixins);
            Py_XDECREF(first);
            if (bases == nullptr)
            {
                return nullptr;
            }
            g_types[flags] = reinterpret_cast<PyTypeObject*>(PyType_FromSpecWithBases(&spec, bases));
            Py_DECREF(bases);
            return g_types[flags];
        }

        // what a Python object can do, for its PyProxy
        inline int py_flags(PyObject* o)
        {
            PyTypeObject* type = Py_TYPE(o);
            int flags = 0;
            if (type->tp_call != nullptr)
            {
                flags |= PY_CALLABLE;
            }
            if (type->tp_as_async != nullptr && type->tp_as_async->am_await != nullptr)
            {
                flags |= PY_AWAITABLE;
            }
            if (type->tp_iter != nullptr)
            {
                flags |= PY_ITERABLE;
            }
            if (PyIter_Check(o))
            {
                flags |= PY_ITERATOR;
            }
            if (PyGen_Check(o))
            {
                flags |= PY_GENERATOR;
            }
            // (len() is implemented by one of two type slots)
            if ((type->tp_as_sequence != nullptr && type->tp_as_sequence->sq_length != nullptr)
                || (type->tp_as_mapping != nullptr && type->tp_as_mapping->mp_length != nullptr))
            {
                flags |= PY_SIZED;
            }
            return flags;
        }

        // an int that is no JS number: its decimal digits, freed by JS
        bool bigint_to_slot(PyObject* o, Slot* slot)
        {
            PyObject* digits = PyObject_Str(o);
            if (digits == nullptr)
            {
                return false;
            }
            Py_ssize_t len;
            const char* utf8 = PyUnicode_AsUTF8AndSize(digits, &len);
            char* copy = utf8 != nullptr ? static_cast<char*>(std::malloc(len + 1)) : nullptr;
            if (copy != nullptr)
            {
                std::memcpy(copy, utf8, len + 1);
                slot->tag = T_BIGINT | T_OWNED;
                slot->aux = static_cast<int32_t>(len);
                slot->num = ptr_to_num(copy);
            }
            else if (utf8 != nullptr)
            {
                PyErr_NoMemory();
            }
            Py_DECREF(digits);
            return copy != nullptr;
        }

        inline bool int_to_slot(PyObject* o, Slot* slot)
        {
            int overflow;
            const long long value = PyLong_AsLongLongAndOverflow(o, &overflow);
            constexpr long long limit = 1LL << 53;
            if (overflow == 0 && value > -limit && value < limit)
            {
                if (value == -1 && PyErr_Occurred())
                {
                    return false;
                }
                slot->tag = T_FLOAT;
                slot->num = static_cast<double>(value);
                return true;
            }
            return bigint_to_slot(o, slot);
        }

        inline bool str_to_slot(PyObject* o, Slot* slot)
        {
            Py_ssize_t len;
            const char* utf8 = PyUnicode_AsUTF8AndSize(o, &len);
            if (utf8 == nullptr)
            {
                return false;
            }
            slot->tag = T_STR;
            slot->aux = static_cast<int32_t>(len);
            slot->num = ptr_to_num(utf8);
            return true;
        }
    }

    Hooks& hooks()
    {
        return g_hooks;
    }

    void js_proxy_forget_types()
    {
        // (the base type, index 0, stays: it has no mixins and is the
        // `JSProxy` everybody already refers to)
        for (int flags = 1; flags < JS_FLAG_END; ++flags)
        {
            Py_CLEAR(g_types[flags]);
        }
    }

    int js_proxy_handle(PyObject* o)
    {
        return is_js_proxy(o) ? as_proxy(o)->handle : 0;
    }

    PyObject* js_proxy_new(int handle, int flags, int this_handle)
    {
        PyTypeObject* type = type_for(flags & (JS_FLAG_END - 1));
        JsProxyObject* proxy = type != nullptr ? PyObject_New(JsProxyObject, type) : nullptr;
        if (proxy == nullptr)
        {
            pyjs_js_free(handle, this_handle);
            return nullptr;
        }
        proxy->handle = handle;
        proxy->this_handle = this_handle;
        proxy->vectorcall = (flags & JS_CALLABLE) ? js_proxy_vectorcall : nullptr;
        return reinterpret_cast<PyObject*>(proxy);
    }

    // Python object -> slot: what JavaScript gets for a Python value.
    //
    //     None                 -> undefined
    //     jsnull               -> null
    //     True / False         -> true / false
    //     int                  -> number (BigInt if it does not fit a number)
    //     float                -> number
    //     str                  -> string
    //     a JSProxy            -> the JavaScript object it stands for
    //     anything else        -> a PyProxy: the object stays in Python and
    //                             JavaScript gets a stand-in for it
    //
    // The checks are ordered by how common the types are, and compare the
    // type pointer directly: this function runs for every argument of every
    // call into JavaScript. Subclasses (rare) are handled after that.
    bool to_slot(PyObject* o, Slot* slot)
    {
        if (o == Py_None)
        {
            slot->tag = T_UNDEF;
            return true;
        }
        PyTypeObject* type = Py_TYPE(o);
        // the exact types first
        if (type == &PyUnicode_Type)
        {
            return str_to_slot(o, slot);
        }
        if (type == &PyLong_Type)
        {
            return int_to_slot(o, slot);
        }
        if (type == &PyFloat_Type)
        {
            slot->tag = T_FLOAT;
            slot->num = PyFloat_AS_DOUBLE(o);
            return true;
        }
        if (type == &PyBool_Type)
        {
            slot->tag = o == Py_True ? T_TRUE : T_FALSE;
            return true;
        }
        if (is_js_proxy(o))
        {
            slot->tag = T_JS;
            slot->aux = as_proxy(o)->handle;
            return true;
        }
        if (o == g_hooks.jsnull)
        {
            slot->tag = T_NULL;
            return true;
        }
        // subclasses
        if (PyUnicode_Check(o))
        {
            return str_to_slot(o, slot);
        }
        if (PyLong_Check(o))
        {
            if (g_hooks.bigint_type != nullptr && PyObject_TypeCheck(o, reinterpret_cast<PyTypeObject*>(g_hooks.bigint_type)))
            {
                return bigint_to_slot(o, slot);
            }
            return int_to_slot(o, slot);
        }
        if (PyFloat_Check(o))
        {
            slot->tag = T_FLOAT;
            slot->num = PyFloat_AS_DOUBLE(o);
            return true;
        }
        // A JSException (a JavaScript Error that came to python): JavaScript
        // gets the Error itself back.
        if (g_hooks.jsexception_type != nullptr
            && PyObject_TypeCheck(o, reinterpret_cast<PyTypeObject*>(g_hooks.jsexception_type)))
        {
            PyObject* error = PyObject_GetAttrString(o, "js_error");
            if (error == nullptr)
            {
                PyErr_Clear();
            }
            else
            {
                const int handle = js_proxy_handle(error);
                // (`o` keeps its js_error, and with it the handle, alive)
                Py_DECREF(error);
                if (handle != 0)
                {
                    slot->tag = T_JS;
                    slot->aux = handle;
                    return true;
                }
            }
        }
        // Any other object: JavaScript gets a PyProxy. The slot carries the
        // address of the object and what it can do (so that JavaScript need
        // not ask). Py_NewRef adds one reference to the object: it belongs
        // to the PyProxy, which keeps the object alive and gives the
        // reference back when it is destroyed (pyjs_decref in py_entry.cpp).
        slot->tag = T_PY;
        slot->aux = py_flags(o);
        slot->num = ptr_to_num(Py_NewRef(o));
        return true;
    }

    // slot -> Python object: what Python gets for a JavaScript value. The
    // reverse of to_slot (the table is in src/js/codec.ts, `encode`). Always
    // returns a new reference; nullptr means a Python exception was set.
    PyObject* from_slot(Slot* slot)
    {
        switch (slot->tag)
        {
            case T_UNDEF:
                Py_RETURN_NONE;
            case T_NULL:
                return Py_NewRef(g_hooks.jsnull != nullptr ? g_hooks.jsnull : Py_None);
            case T_FALSE:
                Py_RETURN_FALSE;
            case T_TRUE:
                Py_RETURN_TRUE;
            case T_INT:
            {
                const double value = slot->num;
                if (value >= -2147483648.0 && value <= 2147483647.0)
                {
                    return PyLong_FromLong(static_cast<long>(value));
                }
                return PyLong_FromDouble(value);
            }
            case T_FLOAT:
                return PyFloat_FromDouble(slot->num);
            case T_STR:
                return PyUnicode_DecodeUTF8(num_to_ptr<char>(slot->num), slot->aux, "surrogatepass");
            case T_STR | T_OWNED:
            {
                char* utf8 = num_to_ptr<char>(slot->num);
                PyObject* str = PyUnicode_DecodeUTF8(utf8, slot->aux, "surrogatepass");
                std::free(utf8);
                return str;
            }
            case T_BIGINT:
            case T_BIGINT | T_OWNED:
            {
                // (NUL terminated)
                char* digits = num_to_ptr<char>(slot->num);
                PyObject* value = PyLong_FromString(digits, nullptr, 10);
                if (slot->tag & T_OWNED)
                {
                    std::free(digits);
                }
                if (value == nullptr || g_hooks.bigint_type == nullptr)
                {
                    return value;
                }
                PyObject* bigint = PyObject_CallOneArg(g_hooks.bigint_type, value);
                Py_DECREF(value);
                return bigint;
            }
            case T_JS:
            {
                PyObject* proxy = js_proxy_new(slot->aux, slot->i.a, slot->i.b);
                if (proxy == nullptr || !(slot->i.a & JS_ERROR) || g_hooks.jsexception_type == nullptr)
                {
                    return proxy;
                }
                // a JavaScript Error: a JSException holding the proxy (PEP 818)
                PyObject* exception = PyObject_CallOneArg(g_hooks.jsexception_type, proxy);
                Py_DECREF(proxy);
                return exception;
            }
            case T_PY:
                // a PyProxy coming back: the Python object itself
                return Py_NewRef(num_to_ptr<PyObject>(slot->num));
            case T_ERROR:
                raise_from_slot(slot);
                return nullptr;
            default:
                PyErr_Format(PyExc_SystemError, "pyjs: unknown slot tag %d", slot->tag);
                return nullptr;
        }
    }

    PyObject* js_global(int which)
    {
        Slot out;
        const int rc = pyjs_js_op(OP_GLOBAL, which, 0.0, 0.0, ptr_to_num(&out));
        return result(rc, &out);
    }

    PyObject* create_proxy(PyObject* obj, bool always, bool roundtrip)
    {
        Slot in, out;
        if (!to_slot(obj, &in))
        {
            return nullptr;
        }
        if (in.tag != T_PY)
        {
            if (always)
            {
                // a JS primitive / JS object: there is nothing to proxy
                release_slots(&in, 1);
                PyErr_Format(PyExc_TypeError, "cannot create a proxy of a '%s' (it converts to a JavaScript value)",
                             Py_TYPE(obj)->tp_name);
                return nullptr;
            }
            release_slots(&in, 1);
            return Py_NewRef(obj);
        }
        // (the `h` argument of the operation carries `roundtrip`)
        const int rc = pyjs_js_op(OP_CREATE_PROXY, roundtrip ? 1 : 0, ptr_to_num(&in), 0.0, ptr_to_num(&out));
        return result(rc, &out);
    }

    PyObject* run_sync(PyObject* promise)
    {
        const int handle = js_proxy_handle(promise);
        if (handle == 0)
        {
            PyErr_SetString(PyExc_TypeError, "run_sync: a JSProxy of a promise is required");
            return nullptr;
        }
        Slot out;
        // suspends this whole call stack until the promise settled (other
        // Python code runs meanwhile, see src/stack_switching.c)
        const int token = pyjs_js_await(handle, ptr_to_num(&out));
        if (token == 0)
        {
            return result(RC_ERROR, &out);
        }
        const int rc = pyjs_js_resume(token, ptr_to_num(&out));
        return result(rc, &out);
    }

    bool js_proxy_init(PyObject* module)
    {
        PyTypeObject* base = type_for(0);
        return base != nullptr && PyModule_AddObjectRef(module, "JSProxy", reinterpret_cast<PyObject*>(base)) == 0;
    }
}
