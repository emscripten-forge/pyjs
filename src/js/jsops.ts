// Python -> JavaScript: what the EM_JS functions of src/js_proxy.cpp /
// src/module.cpp call (a JSProxy operating on its JS object). Arguments
// arrive as slots, the result is written into a slot (codec.ts).
//
// THE RULE OF THIS FILE: no function here may throw. A JavaScript exception
// that leaves one of them would travel through the wasm frames of CPython,
// which are not prepared for that (no cleanup runs, the interpreter is left
// in an undefined state). So every function catches everything and reports
// an error as return code + the thrown value in the result slot (`fail`).
// A function without a result slot (bufferCopy) returns a return code only.
import {
  PYPROXY,
  pyProxyJsFlags,
  bindThis,
  decode,
  encode,
  hFree,
  hGet,
  hNew,
  isSequence,
  jsFlags,
  takeBorrowed,
  utf8,
  writeAuxAndNum,
  writeJsError,
  writeJsObject,
  writePythonError,
} from "./codec";
import { TOO_DEEP, copyOfMemory, fromStream, toStream } from "./deep";
import { canRunSync, jspi } from "./jspi";
import { PythonError, destroyBorrowed } from "./pyproxy";
import { StackState } from "./stack_state";

/** return codes (JsRc in src/js_proxy.cpp) */
const enum Rc {
  OK = 0,
  ERROR = 1,
  NO_ATTR = 2,
  NO_INDEX = 3,
  NO_KEY = 4,
  STOP = 5,
  GENERIC = 6,
  UNSUPPORTED = 7, // the object cannot do this: a TypeError in python
  TOO_DEEP = 9, // only toPy: nested too deeply, a RecursionError in python
}

/** operations of `op` (JsOp in src/js_proxy.cpp) */
const enum Op {
  GETITEM = 0,
  SETITEM = 1,
  DELITEM = 2,
  LEN = 3,
  CONTAINS = 4,
  BOOL = 5,
  REPR = 6,
  TYPEOF = 7,
  ITER = 8,
  NEXT = 9,
  SAME = 10,
  GLOBAL = 11,
  CREATE_PROXY = 12,
  ID = 13,
}

/**
 * Report "the operation threw `error`" to Python: writes the error into the
 * result slot `out` and returns Rc.ERROR. Every function here ends its
 * `catch` with this, because a JavaScript exception must never travel into
 * wasm: Python learns about it from the return code and raises its own.
 */
function fail(error: any, out: number): number {
  if (error instanceof PythonError && error.__pyjs_exception !== 0) {
    // The "JavaScript error" is really a Python exception on its way through
    // JavaScript: Python called JS, JS called a Python function, and that one
    // raised. Hand Python its own exception back, so that the caller sees
    // e.g. the original KeyError and not a wrapped JavaScript error.
    writePythonError(out, error.__pyjs_exception);
  } else {
    // (anything can be thrown: only objects have features worth looking at)
    const flags = error !== null && typeof error === "object" ? jsFlags(error) : 0;
    writeJsError(out, error, flags);
  }
  return Rc.ERROR;
}

/** a promise or thenable */
function isThenable(value: any): boolean {
  return value !== null && typeof value === "object" && typeof value.then === "function";
}

/** a (sync or async) generator object, as a generator function returns it */
function isGenerator(value: any): boolean {
  const tag = Object.prototype.toString.call(value);
  return tag === "[object Generator]" || tag === "[object AsyncGenerator]";
}

/** a real promise (as an async function returns it), not just any object with a `then` */
function isPromise(value: any): boolean {
  return Object.prototype.toString.call(value) === "[object Promise]";
}

// destroys the argument proxies of a call once what it returned (a generator,
// a thenable) is garbage collected
const laterArguments = new FinalizationRegistry((proxies: any[]) => destroyBorrowed(proxies));

/**
 * The proxies created for the arguments of a call are destroyed after it.
 * When that is depends on what the call returned:
 *   - a promise (an async function was called: its body goes on later):
 *     when the promise settles
 *   - a generator, or another object with a `then` method: when the garbage
 *     collector frees that object (its code may use the arguments any time
 *     until then)
 *   - anything else: now
 */
function releaseBorrowed(proxies: any[], result: any): void {
  if (result !== null && typeof result === "object" && result[PYPROXY] !== undefined) {
    // A Python object came back (e.g. `(x) => x`, also with a coroutine as
    // x: a PyProxy of an awaitable has a `then`, and calling it would START
    // the coroutine behind the caller's back). The call is over.
    destroyBorrowed(proxies);
    return;
  }
  if (isPromise(result)) {
    // Not right when the promise settles but one step later
    // (queueMicrotask). The promise may settle WITH one of the proxies
    // (`async (x) => x`): whoever awaits it (python) is notified in the
    // same round as this callback and must still find the proxy alive to
    // get the Python object out of it.
    const release = () => queueMicrotask(() => destroyBorrowed(proxies));
    result.then(release, release);
    return;
  }
  if (isGenerator(result) || isThenable(result)) {
    // A generator function was called: its body runs later, step by step,
    // and uses the arguments then. The same may be true for an object that
    // merely has a `then` method. Its `then` must not be called to find
    // out when it is done: some objects only start their work when `then`
    // is called (the query builders of database libraries), and whoever
    // awaits it later would start it a second time. So in both cases the
    // arguments live as long as the returned object.
    laterArguments.register(result, proxies);
    return;
  }
  destroyBorrowed(proxies);
}

/**
 * Python calls a JavaScript function: `f(1, 2)` in Python, where `f` is a
 * JSProxy of a JS function.
 *
 * Who calls this: CPython calls the proxy's vectorcall (js_proxy_vectorcall
 * -> call_js in src/js_proxy.cpp), which writes the arguments into slots and
 * calls the EM_JS function pyjs_js_call, a one-liner calling this. Also for
 * `f.new(...)` (construct = 1: JavaScript's `new f(...)`).
 *
 * The parameters (all numbers: they come from wasm):
 *   fn         handle of the function
 *   self       handle of `this` (0: none), for a method fetched from an
 *              object (`obj.method` in Python remembers `obj`)
 *   args       address of the argument slots: npos positional values, nkw
 *              keyword values, nkw keyword names
 *   construct  1: `new fn(...)`
 *   out        address of the result slot
 * Keyword arguments become one trailing object (`f(1, a=2)` -> `f(1, {a: 2})`),
 * as JavaScript functions take options that way.
 *
 * Returns a return code (Rc); the result or the thrown value is in `out`.
 */
export function call(
  fn: number,
  self: number,
  args: number,
  npos: number,
  nkw: number,
  construct: number,
  out: number
): number {
  let borrowed: any[] | null = null;
  try {
    const f = hGet(fn);
    let result;
    if (nkw === 0 && construct === 0 && npos <= 3) {
      // the common cases without an arguments array
      const a = npos > 0 ? decode(args, false) : undefined;
      const b = npos > 1 ? decode(args + 16, false) : undefined;
      const c = npos > 2 ? decode(args + 32, false) : undefined;
      borrowed = takeBorrowed();
      if (self === 0) {
        result = npos === 0 ? f() : npos === 1 ? f(a) : npos === 2 ? f(a, b) : f(a, b, c);
      } else {
        // (Reflect.apply and not f.call(...): something callable need not
        // have a `call` method, e.g. a function whose prototype was replaced)
        const thisArg = hGet(self);
        result =
          npos === 0
            ? Reflect.apply(f, thisArg, [])
            : npos === 1
              ? Reflect.apply(f, thisArg, [a])
              : npos === 2
                ? Reflect.apply(f, thisArg, [a, b])
                : Reflect.apply(f, thisArg, [a, b, c]);
      }
    } else {
      const values = new Array(npos);
      for (let i = 0; i < npos; i++) {
        values[i] = decode(args + 16 * i, false);
      }
      if (nkw > 0) {
        const kwargs: Record<string, any> = {};
        for (let i = 0; i < nkw; i++) {
          const name = decode(args + 16 * (npos + nkw + i), false);
          const value = decode(args + 16 * (npos + i), false);
          if (name === "__proto__") {
            // (`kwargs["__proto__"] = x` would set the prototype of the
            // object instead of creating a property of that name)
            Object.defineProperty(kwargs, name, { value, enumerable: true, configurable: true, writable: true });
          } else {
            kwargs[name] = value;
          }
        }
        values.push(kwargs);
      }
      borrowed = takeBorrowed();
      result =
        construct !== 0
          ? Reflect.construct(f, values)
          : Reflect.apply(f, self === 0 ? undefined : hGet(self), values);
    }
    // The result is written BEFORE the borrowed proxies are destroyed: a
    // function may return one of its arguments (`(x) => x`), and a destroyed
    // proxy can no longer say which Python object it stood for.
    encode(result, out, false);
    if (borrowed !== null) {
      const proxies = borrowed;
      borrowed = null;
      releaseBorrowed(proxies, result);
    }
    return Rc.OK;
  } catch (error) {
    borrowed ??= takeBorrowed();
    if (borrowed !== null) {
      destroyBorrowed(borrowed);
    }
    return fail(error, out);
  }
}

/** obj[name]: a function remembers obj as its `this` */
export function getattr(h: number, name: number, out: number): number {
  try {
    const obj = hGet(h);
    const key = hGet(name);
    const value = obj[key];
    if (value === undefined && !(key in obj)) {
      return Rc.NO_ATTR;
    }
    encode(value, out, false);
    if (typeof value === "function") {
      // python does `f = obj.name` now and `f(...)` later: the function must
      // remember `obj` to run as its method then (see bindThis in codec.ts)
      bindThis(out, obj);
    }
    return Rc.OK;
  } catch (error) {
    return fail(error, out);
  }
}

/** obj[name] = value, or delete obj[name] (value: 0) */
export function setattr(h: number, name: number, value: number, out: number): number {
  try {
    const obj = hGet(h);
    if (value === 0) {
      delete obj[hGet(name)];
    } else {
      // a Python object stored in JS: its proxy lives until it is destroyed
      obj[hGet(name)] = decode(value, true);
    }
    return Rc.OK;
  } catch (error) {
    return fail(error, out);
  }
}

// names clashing with python keywords are written with a trailing underscore
const PYTHON_KEYWORDS = new Set(
  (
    "False None True and as assert async await break class continue def del elif else except " +
    "finally for from global if import in is lambda nonlocal not or pass raise return try while with yield"
  ).split(" ")
);

/** handle of the JS property name for a Python attribute name (utf8) */
export function name(ptr: number, len: number): number {
  let str = utf8(ptr, len);
  // `from_` is the property `from`. More underscores lose exactly one
  // (`from__` is the property `from_`), so that every property name can be
  // written in python.
  if (str.endsWith("_") && PYTHON_KEYWORDS.has(str.replace(/_+$/, ""))) {
    str = str.slice(0, -1);
  }
  return hNew(str);
}

/**
 * A JSProxy died in Python: release its handles (see "handles" in codec.ts).
 *
 * Who calls this: the C++ side, when the reference count of a JSProxy drops
 * to 0 (js_proxy_dealloc in src/js_proxy.cpp -> the EM_JS function
 * pyjs_js_free -> this). Afterwards JavaScript's garbage collector may
 * reclaim the JS object, unless something else still references it.
 *
 * Why two handles: a JSProxy holds up to two (struct JsProxyObject there):
 *   h    the JS object the proxy stands for
 *   h2   only for a function fetched from an object (`f = obj.method`):
 *        the handle of `obj`, kept so that `f()` runs with `this` = obj
 *        (0 for every other proxy: hFree ignores 0)
 * Both are freed with one call instead of two, because every call from wasm
 * into JavaScript costs time and proxies die very often. (deep.cpp also uses
 * it, with h2 = 0, to drop a handle it no longer needs.)
 */
export function free(h: number, h2: number): void {
  hFree(h);
  hFree(h2);
}

// js_id: a number per object
const ids = new WeakMap<object, number>();
let nextId = 1;

/**
 * Is `obj` one of the list types of the DOM (the result of
 * document.querySelectorAll, element.children)? Like an Array, such a list
 * is false in python when it is empty.
 */
function isDomList(obj: any): boolean {
  const tag = Object.prototype.toString.call(obj);
  return tag === "[object NodeList]" || tag === "[object HTMLCollection]";
}

/** index of a sequence: negative from the end; -1 if out of range */
function index(obj: any, key: number): number {
  const n = obj.length;
  const i = key < 0 ? key + n : key;
  return i >= 0 && i < n ? i : -1;
}

/** obj[key] of an Array / typed array; other objects: Rc.GENERIC (see op) */
export function getindex(h: number, key: number, out: number): number {
  try {
    const obj = hGet(h);
    if (!isSequence(obj)) {
      return Rc.GENERIC;
    }
    const i = index(obj, key);
    if (i < 0) {
      return Rc.NO_INDEX;
    }
    const value = obj[i];
    if (value === undefined && !(i in obj)) {
      // a hole of a sparse Array (`[1, , 3][1]`): there is no item
      return Rc.NO_INDEX;
    }
    encode(value, out, false);
    return Rc.OK;
  } catch (error) {
    return fail(error, out);
  }
}

/**
 * One of the less frequent operations Python does on a JS object, selected by
 * the number `op`: `proxy[key]`, `proxy[key] = value`, `del proxy[key]`,
 * `len(proxy)`, `x in proxy`, `bool(proxy)`, `repr(proxy)`, `proxy.typeof`,
 * `iter(proxy)` / `next(it)`, `proxy == other`, `hash(proxy)`, and two that
 * are no operation on an object (GLOBAL: the JSProxy of globalThis / Module;
 * CREATE_PROXY: a PyProxy for a Python object).
 *
 * Where it is needed: every one of those Python operations ends up here. The
 * C++ side (js_proxy.cpp: js_proxy_len, js_proxy_contains, ..., through its
 * helper `op` and the EM_JS function pyjs_js_op) writes up to two arguments
 * into slots and calls this with the operation number. The table of all
 * operations, with the Python code that triggers each and the C++ function,
 * is at `enum JsOp` in src/js_proxy.cpp (numbers identical to `Op` above).
 *
 * Why one long function and not one per operation: each separate function
 * would be one more import of the wasm module (one EM_JS function each).
 * The four most frequent operations (call, getattr, getindex, setattr) have
 * their own, for speed; all the rarely used ones share this entry and are
 * told apart by the switch below. Each case is short; the length comes from
 * their number.
 *
 * Parameters: h the object (handle), arg / arg2 addresses of argument slots
 * (0: unused), out the result slot. Returns an Rc.
 */
export function op(op: Op, h: number, arg: number, arg2: number, out: number): number {
  // The proxies decode() creates for Python objects among the arguments
  // (say the value of `proxy[k] = some_list`) are "borrowed": they may only
  // live during this operation (see "Borrowed" proxies in codec.ts). decode()
  // collects them; takeBorrowed() hands that list to this call right after
  // decoding, and it is destroyed after the switch, whatever happened.
  let borrowed: any[] | null = null;
  try {
    const obj = hGet(h);
    let result;
    // What to report when the operation did not throw. The cases set it to
    // e.g. Rc.NO_KEY instead of returning right away, so that all of them
    // pass the cleanup of the borrowed proxies behind the switch.
    let rc = Rc.OK;
    switch (op) {
      case Op.GETITEM: {
        const key = decode(arg, false);
        borrowed = takeBorrowed();
        // By position: Arrays, typed arrays, and "array-likes" such as a
        // NodeList (which have a length but no get() method).
        if (
          typeof key === "number" &&
          (isSequence(obj) || (typeof obj.get !== "function" && typeof obj.length === "number"))
        ) {
          const i = index(obj, key);
          if (i < 0) {
            rc = Rc.NO_INDEX;
            break;
          }
          result = obj[i];
          if (result === undefined && !(i in obj)) {
            // a hole of a sparse Array (`[1, , 3][1]`): there is no item
            rc = Rc.NO_INDEX;
          }
        } else {
          // A container with a get() method, like a Map. (Python only
          // offers obj[key] for objects that are a sequence or have get():
          // flag GETITEM in codec.ts. So there is no third case.)
          result = obj.get(key);
          // get() answers undefined for a missing key, but undefined can
          // also be a stored value: ask has() to tell the two apart, so
          // that python gets a KeyError only for a key that is not there.
          if (result === undefined && typeof obj.has === "function" && !obj.has(key)) {
            rc = Rc.NO_KEY;
          }
        }
        break;
      }
      case Op.SETITEM: {
        const key = decode(arg, false);
        borrowed = takeBorrowed();
        const value = decode(arg2, true);
        if (typeof key === "number" && isSequence(obj)) {
          const i = index(obj, key);
          if (i < 0) {
            rc = Rc.NO_INDEX;
            break;
          }
          obj[i] = value;
        } else {
          // a container with a set() method, like a Map (flag SETITEM)
          obj.set(key, value);
        }
        break;
      }
      case Op.DELITEM: {
        // `del obj[key]`
        const key = decode(arg, false);
        borrowed = takeBorrowed();
        if (typeof key === "number" && Array.isArray(obj)) {
          // like `del some_list[i]`: the element is removed and the ones
          // behind it move up
          const i = index(obj, key);
          if (i < 0) {
            rc = Rc.NO_INDEX;
            break;
          }
          obj.splice(i, 1);
        } else if (typeof obj.delete !== "function") {
          // e.g. a typed array: its length is fixed
          rc = Rc.UNSUPPORTED;
        } else if (obj.delete(key) === false) {
          // Map, Set, ...: their delete() method. It answers false when
          // there was no such key: a KeyError in python, as for a dict.
          rc = Rc.NO_KEY;
        }
        break;
      }
      case Op.LEN:
        // (`size` first, as pyodide: what a Map / Set has)
        result = obj.size ?? obj.length;
        if (typeof result !== "number") {
          rc = Rc.UNSUPPORTED;
        }
        break;
      case Op.CONTAINS: {
        const value = decode(arg, false);
        borrowed = takeBorrowed();
        result = typeof obj.has === "function" ? obj.has(value) : obj.includes(value);
        break;
      }
      case Op.BOOL:
        // Like python containers, an empty container is false. Everything
        // else is true (the same rules as pyodide):
        //   - size 0: a Map / Set ... (but not an HTML element: `size` is
        //     an attribute of <select> and <input>)
        //   - length 0: only for Arrays and typed arrays. Other things have
        //     a `length` that says nothing about being "empty": the length
        //     of a function is its number of parameters, an HTML <select>
        //     has one, ...
        //   - byteLength 0: an ArrayBuffer
        result = !(
          (obj.size === 0 && !/HTML[A-Za-z]*Element/.test(Object.prototype.toString.call(obj))) ||
          (obj.length === 0 && (isSequence(obj) || isDomList(obj))) ||
          obj.byteLength === 0
        );
        break;
      case Op.REPR: {
        // obj.toString(). Objects that have no toString method at all
        // (`Object.create(null)`, module namespace objects, a getter that
        // throws) get what Object's toString says about them, e.g.
        // "[object Module]". An error thrown BY a toString method is
        // reported.
        let toString;
        try {
          toString = obj.toString;
        } catch {
          // (no usable toString)
        }
        result =
          typeof toString === "function" ? String(toString.call(obj)) : Object.prototype.toString.call(obj);
        break;
      }
      case Op.TYPEOF:
        result = typeof obj;
        break;
      case Op.ITER:
        result = obj[Symbol.iterator]();
        break;
      case Op.NEXT: {
        const step = obj.next();
        if (step.done) {
          return Rc.STOP;
        }
        result = step.value;
        break;
      }
      case Op.SAME:
        result = obj === decode(arg, false);
        borrowed = takeBorrowed();
        break;
      case Op.GLOBAL:
        result = h === 0 ? globalThis : Module;
        break;
      case Op.CREATE_PROXY: {
        // pyjs.create_proxy(obj). `arg` holds the Python object; decode makes
        // the PyProxy for it (owned: it lives until destroy()).
        const proxy = decode(arg, true);
        // Now that PyProxy must go back to Python as a JS object, i.e. as a
        // JSProxy wrapping the PyProxy. encode() cannot be used: it would
        // recognize the PyProxy and hand Python its own object back
        // (unwrapped), which is exactly what create_proxy must not do.
        //
        // `h` says whether it is a "roundtrip" proxy (see encode in
        // codec.ts). The Python type of the JSProxy depends on what the JS
        // object can do, see pyProxyJsFlags.
        const state = proxy[PYPROXY];
        state.roundtrip = h !== 0;
        writeJsObject(out, proxy, pyProxyJsFlags(state));
        return Rc.OK;
      }
      case Op.ID: {
        result = ids.get(obj);
        if (result === undefined) {
          result = nextId++;
          ids.set(obj, result);
        }
        break;
      }
      default:
        throw new Error(`pyjs: unknown operation ${op}`);
    }
    if (borrowed !== null) {
      destroyBorrowed(borrowed);
      borrowed = null;
    }
    if (rc !== Rc.OK) {
      return rc;
    }
    encode(result, out, false);
    return Rc.OK;
  } catch (error) {
    borrowed ??= takeBorrowed();
    if (borrowed !== null) {
      destroyBorrowed(borrowed);
    }
    return fail(error, out);
  }
}

/**
 * to_py(): write the JS object `h` and everything in it (`depth` levels of
 * containers, -1: all) as one stream of slots, which the C side turns into
 * Python objects. deep.ts explains the stream and what is written to `out`.
 */
export function toPy(h: number, depth: number, limit: number, fresh: number, out: number): number {
  try {
    toStream(h, depth, limit, fresh, out);
    return Rc.OK;
  } catch (error) {
    if (error === TOO_DEEP) {
      // nested deeper than `limit` levels: a RecursionError in Python
      return Rc.TOO_DEEP;
    }
    return fail(error, out);
  }
}

/**
 * to_js(): build the JS value described by the stream of slots at `stream`
 * (written by the C side from a Python structure); `out` gets the result.
 */
export function toJs(stream: number, out: number): number {
  try {
    fromStream(stream, out);
    return Rc.OK;
  } catch (error) {
    return fail(error, out);
  }
}

/**
 * The JavaScript half of `run_sync(promise)` (JSPI): waits for the promise,
 * while the Python call stack is suspended.
 *
 * Which promise: `run_sync` (module/pyjs/core.py) never hands in the user's
 * promise directly, but one settled by a done callback of an asyncio future
 * of it. That callback runs in the event loop's queue (scheduler.ts), so the
 * stack resumes in turn with the asyncio tasks, not ahead of tasks that were
 * woken before it (as in pyodide).
 *
 * Why the promise is a number: like every JS object Python refers to, it is
 * passed as its handle (see "handles" in codec.ts). Python holds a JSProxy of
 * the promise; the C side passes the proxy's handle `h`, and `hGet(h)` here
 * is the promise itself. (Wasm can only pass numbers to JavaScript.)
 *
 * This function is wrapped in `WebAssembly.Suspending` (the EM_JS function
 * pyjs_js_await in src/js_proxy.cpp): when it returns a promise, the wasm
 * code that called it is suspended until that promise settles, then resumes
 * with the number the promise resolved to: a token for jspiResume, which the
 * C side calls right away. When it returns 0 instead (run_sync is not
 * possible here; the error is in `out`), nothing is suspended.
 *
 * While the task is suspended, other Python code runs, also other tasks that
 * suspend in turn. So before suspending, the task's state is moved out of the
 * way, and jspiResume puts it back, from inside the resumed wasm before any
 * of the task's code runs (doing it in the promise callback would leave a gap
 * in which other code could run on the restored state):
 *   - its part of CPython's thread state (frames, exception state, context):
 *     pyjs_capture_task_state / pyjs_restore_task_state (src/stack_switching.c)
 *   - its data on the C stack: StackState (stack_state.ts)
 */
export function jspiAwait(h: number, out: number): number | Promise<number> {
  if (!canRunSync()) {
    fail(new Error("pyjs: run_sync is not possible here (see pyjs.can_run_sync())"), out);
    return 0;
  }
  const promise = hGet(h);
  const taskState = wasmExports.pyjs_capture_task_state();
  if (!taskState) {
    fail(new Error("pyjs: run_sync outside of a promising call (or out of memory)"), out);
    return 0;
  }
  const task: SuspendedTask = { taskState, stackState: new StackState(), ok: false, value: undefined };
  const token = nextToken++;
  suspendedTasks.set(token, task);
  // back at the event loop level until the task resumes
  jspi.depth -= 1;
  jspi.canSuspend = false;
  return Promise.resolve(promise).then(
    (value) => {
      task.ok = true;
      task.value = value;
      // The promise of an async JavaScript function may resolve to one of
      // its Python arguments (`async (x) => x`). That is a borrowed proxy,
      // destroyed one step after the promise settled, which is BEFORE the
      // suspended task runs again and reads the value. So a proxy of our
      // own is kept for that moment (released in jspiResume).
      const state = value !== null && typeof value === "object" ? value[PYPROXY] : undefined;
      if (state !== undefined && !state.owned && state.ptr !== 0) {
        task.value = task.copy = value.copy();
      }
      return token;
    },
    (error) => {
      task.value = error;
      return token;
    },
  );
}

/** a task suspended in run_sync (jspiAwait), until jspiResume */
interface SuspendedTask {
  /** address of its saved thread state (pyjs_capture_task_state) */
  taskState: number;
  stackState: StackState;
  /** how the promise settled: value or error */
  ok: boolean;
  value: any;
  /** an owned PyProxy made to keep `value` usable, destroyed by jspiResume */
  copy?: any;
}

const suspendedTasks = new Map<number, SuspendedTask>();
let nextToken = 1;

/**
 * The second half of run_sync: the task was resumed (it runs again, called by
 * the C side right after pyjs_js_await returned `token`). Put its state back,
 * then write the promise's value / error into `out` (which lives on the
 * task's C stack: only valid after restore()).
 */
export function jspiResume(token: number, out: number): number {
  const task = suspendedTasks.get(token)!;
  suspendedTasks.delete(token);
  task.stackState.restore();
  wasmExports.pyjs_restore_task_state(task.taskState);
  jspi.depth += 1;
  jspi.canSuspend = true;
  if (!task.ok) {
    return fail(task.value, out);
  }
  try {
    encode(task.value, out, false);
    return Rc.OK;
  } catch (error) {
    return fail(error, out);
  } finally {
    if (task.copy !== undefined) {
      task.copy.destroy();
    }
  }
}

/** for tests: the number of tasks suspended in run_sync */
export function suspendedTaskCount(): number {
  return suspendedTasks.size;
}

// struct format character -> typed array class. (No "l" / "L", C long: its
// size differs between wasm32 and wasm64, the C side sends it as "i" / "q",
// see js_buffer_format in src/slot.hpp. An unknown character is an error,
// never silently the wrong item size.)
const TYPED_ARRAYS: Record<string, any> = {
  b: Int8Array,
  B: Uint8Array,
  c: Uint8Array,
  "?": Uint8Array,
  h: Int16Array,
  H: Uint16Array,
  i: Int32Array,
  I: Uint32Array,
  q: BigInt64Array,
  Q: BigUint64Array,
  f: Float32Array,
  d: Float64Array,
};

/**
 * A JavaScript typed array for a block of numbers in wasm memory: what
 * Python's `buffer_to_js(obj, view)` (src/module.cpp) gives JavaScript for a
 * Python buffer (bytes, array.array, a numpy array, ...).
 *
 * Why it exists: a Python buffer IS just a block of wasm memory, and JS can
 * look at wasm memory directly. So no element-by-element conversion is
 * needed: a typed array of the right item type (Float64Array for "d", ...)
 * is laid over the same bytes.
 *   view = 1   that typed array itself: no copy at all, but only valid as
 *              long as the Python buffer exists and the wasm memory does not
 *              grow (growing replaces the underlying ArrayBuffer). Used for
 *              short-lived access (JSBuffer.assign).
 *   view = 0   a copy (`slice()`): independent of the Python object, what
 *              to_js returns for buffers.
 * `ptr`, `nitems`: where the items are and how many; `format`: the character
 * code of their struct format character (see TYPED_ARRAYS).
 */
export function typedArray(ptr: number, nitems: number, format: number, view: number, out: number): number {
  try {
    const cls = TYPED_ARRAYS[String.fromCharCode(format)];
    if (cls === undefined) {
      return Rc.ERROR;
    }
    // (a copy also works when the items do not sit at a multiple of their
    // size, see copyOfMemory; a view cannot: an error then)
    const array = view !== 0 ? new cls(HEAPU8.buffer, ptr, nitems) : copyOfMemory(cls, ptr, nitems);
    encode(array, out, false);
    return Rc.OK;
  } catch (error) {
    return fail(error, out);
  }
}

/** the bytes of a typed array / DataView / ArrayBuffer */
function bytesOf(obj: any): Uint8Array {
  return ArrayBuffer.isView(obj) ? new Uint8Array(obj.buffer, obj.byteOffset, obj.byteLength) : new Uint8Array(obj);
}

/** number of bytes (double) and struct format character (aux) of a buffer */
export function bufferInfo(h: number, out: number): number {
  try {
    const obj = hGet(h);
    if (!ArrayBuffer.isView(obj) && !(obj instanceof ArrayBuffer)) {
      return Rc.ERROR;
    }
    let format = "B";
    for (const code of "bBhHiIqQfd") {
      if (obj instanceof TYPED_ARRAYS[code]) {
        format = code;
      }
    }
    // (two plain numbers for the C side, no value: the tag is not used)
    writeAuxAndNum(out, format.charCodeAt(0), obj.byteLength);
    return Rc.OK;
  } catch {
    // (nothing may throw into wasm, see `fail`)
    return Rc.ERROR;
  }
}

/**
 * Copy the bytes of a buffer into the wasm memory at `ptr`, where the C side
 * made room for `size` bytes (the size the buffer had when it was asked).
 * Rc.OK, or Rc.ERROR if the buffer does not have that size any more.
 *
 * Two things can happen to a buffer between "how big are you" and this copy:
 *   - it is detached (transferred away with postMessage / structuredClone;
 *     also every view of the wasm memory itself once that memory grows).
 *     A detached buffer has length 0, and JavaScript THROWS when a view of
 *     it is created. Size 0 asked, nothing to copy: fine.
 *   - it was resized (resizable ArrayBuffer). Copying more than `size` bytes
 *     would write past the room the C side made.
 * Never throws (a JavaScript exception must not travel into wasm).
 */
export function bufferCopy(h: number, ptr: number, size: number): number {
  if (size === 0) {
    return Rc.OK;
  }
  try {
    const bytes = bytesOf(hGet(h));
    if (bytes.length !== size) {
      return Rc.ERROR;
    }
    HEAPU8.set(bytes, ptr);
    return Rc.OK;
  } catch {
    return Rc.ERROR;
  }
}
