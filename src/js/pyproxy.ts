// PyProxy: a JavaScript object standing for a Python object (the mirror
// image of the JSProxy in src/js_proxy.cpp).
//
// WHAT AN "ES PROXY" IS. `Proxy` is a built-in class of JavaScript
// (ECMAScript, hence "ES"): `new Proxy(target, handler)` creates an object
// that intercepts the basic operations done to it. Reading a property, writing
// one, `in`, `delete`, calling it as a function, ... each call a function of
// the `handler` object (the "traps": get, set, has, deleteProperty, apply, ...)
// instead of doing the normal thing. That is exactly what is needed here: a
// PyProxy is such a Proxy whose handler forwards every operation to Python
// (`handler` below):
//
//     JavaScript              handler trap     Python
//     proxy.name              get              getattr(obj, "name")
//     proxy.name = 1          set              setattr(obj, "name", 1)
//     "name" in proxy         has              hasattr(obj, "name")
//     proxy(1, 2)             apply            obj(1, 2)
//     for (x of proxy)        get Symbol.iterator -> iter / next
//
// Plus methods of the proxy itself (destroy, toJs, callKwargs, get / set /
// has / delete for items, then for awaitables, ...), found before the
// Python attributes.
//
// HOW AN OPERATION REACHES PYTHON. Every operation is ONE call from
// JavaScript into wasm, of a function the C++ side exports for this purpose
// ("exports": wasm functions JavaScript can call, defined in
// src/py_entry.cpp: pyjs_call, pyjs_op, ...). The arguments and the result
// travel as slots (codec.ts). A call, `proxy(1, "a")` in JavaScript (the same
// as a diagram: docs/design.md):
//
//   JavaScript            this file                 C++ (py_entry.cpp)
//   proxy(1, "a") ------> handler.apply
//                         callPython: encode the
//                         arguments into slots
//                         pyCall(fn, slots) ------> pyjs_call: from_slot each
//                                                   PyObject_Vectorcall(...)
//                                                   to_slot(result), or
//                                                   write_error (3 slots)
//                         rc = OK / ERROR <-------
//                         OK:    decode(result)
//                         ERROR: throw PythonError
//   result <------------- (a value, or an owned PyProxy)
//
// WHO HOLDS WHAT. A PyProxy owns one reference to its Python object (its
// `State.ptr`); destroy() releases it. See State below.
import { jspi } from "./jspi";
import { enterTask } from "./stack_state";
import {
  PyFlag,
  PYPROXY,
  alloc,
  decode,
  discardSlots,
  encode,
  scratchMark,
  scratchRelease,
  scratchSlots,
  setPyProxyFactory,
  slotNum,
  slotString,
} from "./codec";

/**
 * The operations JavaScript can do on a Python object through a PyProxy
 * (except calling it, which has an export of its own): these are what
 * the methods / traps of a PyProxy end up as. They all go through ONE wasm
 * export, `pyjs_op(op, obj, args, out)` in src/py_entry.cpp, which dispatches
 * on this number; the numbers must be identical to `PyOp` there. (The same
 * idea as JsOp for the other direction: one entry for many operations.)
 *
 *   GETATTR  proxy.name             SETATTR / DELATTR  proxy.name = v / delete
 *   GETITEM  proxy.get(k)           SETITEM / DELITEM  proxy.set(k, v) / proxy.delete(k)
 *   CONTAINS proxy.has(k)           LEN                proxy.length
 *   REPR / STR  repr / str          TYPE               proxy.type
 *   ITER / NEXT for (x of proxy)    IMPORT             pyimport("name")
 *   HASATTR  "name" in proxy (only yes / no: no value comes back that
 *            somebody would have to release)
 */
const enum PyOp {
  GETATTR = 0,
  SETATTR = 1,
  DELATTR = 2,
  GETITEM = 3,
  SETITEM = 4,
  DELITEM = 5,
  CONTAINS = 6,
  LEN = 7,
  REPR = 8,
  STR = 9,
  TYPE = 10,
  ITER = 11,
  NEXT = 12,
  IMPORT = 13,
  HASATTR = 14,
}

/**
 * What the wasm exports (pyjs_call, pyjs_op, ... in src/py_entry.cpp) return:
 * how the Python operation went. The value itself (or the exception) is in the
 * result slot. Python errors never travel into JavaScript as exceptions out
 * of wasm: they are reported this way and thrown here, as PythonError.
 */
const enum Rc {
  OK = 0,
  ERROR = 1, // Python raised: the result slots describe the exception
  NO_ATTR = 2, // the attribute does not exist (AttributeError): `undefined` in JS
  STOP = 5, // the iterator is exhausted (StopIteration)
  // only pyjs_call_promising: the task was not started (the result slots
  // describe the exception), and the C side did not call taskDone
  NOT_ENTERED = 8,
}

/**
 * What a PyProxy knows about its Python object: the internal state of ONE
 * proxy. Each PyProxy (the ES Proxy object users hold) has exactly one State,
 * stored on the proxy's target (`target.state`, see `create`); the handler
 * traps get it from there, the methods of the proxy as `this[PYPROXY]`.
 * Users never see or pass it: functions in this file that take a `state`
 * parameter are internal and are called by the handler / the methods of the
 * proxy.
 */
interface State {
  /** address of the Python object (PyObject*), 0 once destroyed */
  ptr: number;
  /** what the Python object can do (PyFlag: callable, awaitable, ...), computed by the C side */
  flags: number;
  /**
   * true: the proxy owns its reference to the Python object and is registered
   * with the FinalizationRegistry (destroyed when garbage collected).
   * false: "borrowed" (an argument of a call from Python), destroyed when
   * that call ends (see "Borrowed" proxies in codec.ts)
   */
  owned: boolean;
  /** the message of the error for a use after destroy() (one of the two texts below) */
  destroyed: string;
  /** of an awaitable, once it was awaited from JS (`then`): awaited only once */
  promise?: Promise<any>;
  /**
   * made by create_proxy(obj, roundtrip=True): comes back to python as this
   * proxy (JSDoubleProxy), not as `obj` (see encode in codec.ts)
   */
  roundtrip?: boolean;
}

// the texts of the errors for using a proxy after it was destroyed
const DESTROYED_MESSAGE = "This proxy was destroyed: the Python object is no longer accessible.";
const BORROWED_DESTROYED_MESSAGE =
  "This borrowed proxy was automatically destroyed at the end of a function call. " +
  "Try using create_proxy or create_once_callable.";

// The wasm exports used here (functions of src/py_entry.cpp). These are only
// the declarations, with their signatures (all arguments are numbers:
// addresses, counts, flags); the functions are looked up in initPyProxy once
// the wasm module exists.
let pyCall: (fn: number, args: number, npos: number, nkw: number, out: number) => number;
let pyOp: (op: number, obj: number, args: number, out: number) => number;
let pyDecref: (obj: number) => void;
let pyIncref: (obj: number) => void;
// The same as pyCall, but entered with JSPI: the Python code may suspend
// (run_sync), so it returns a promise of the return code. null without JSPI.
let pyCallPromising: ((fn: number, args: number, npos: number, nkw: number, out: number) => Promise<number>) | null =
  null;
// three result slots, allocated once (an error needs 3 slots: type, message,
// exception), reused by every synchronous operation
let result = 0;

// python helper `(awaitable, resolve, reject)`: settles a promise with the
// result of an awaitable (set by the runtime once python runs)
let thenHelper: any = null;

// python `to_js`
let toJsHelper: any = null;

// python `(generator, method, argument) -> {done, value}`
let generatorStepHelper: any = null;

/** the python helpers of PyProxy.then / PyProxy.toJs / generator methods */
export function setPythonHelpers(then: any, toJs: any, generatorStep: any): void {
  thenHelper = then;
  toJsHelper = toJs;
  generatorStepHelper = generatorStep;
}

/**
 * Set up this file once the wasm module exists (called by pyjsCore.init in
 * index.ts, when Python is about to start).
 *
 * The wasm exports (the functions of src/py_entry.cpp) only exist after
 * the wasm module was instantiated, later than this code is loaded. So they
 * are looked up here, once, into the variables above (faster than looking
 * them up on every call). With JSPI, `pyjs_call_promising` is wrapped in
 * WebAssembly.promising: calling it returns a promise, and the Python code it
 * runs may suspend. Finally the result slots are allocated.
 */
export function initPyProxy(): void {
  pyCall = wasmExports.pyjs_call;
  pyOp = wasmExports.pyjs_op;
  pyDecref = wasmExports.pyjs_decref;
  pyIncref = wasmExports.pyjs_incref;
  if (jspi.supported) {
    pyCallPromising = (WebAssembly as any).promising(wasmExports.pyjs_call_promising);
  }
  result = alloc(3 * 16);
}

// The backstop for proxies nobody destroyed.
//
// A PyProxy holds a reference to its Python object, which keeps that object
// alive. The intended release is proxy.destroy(). If the user forgets it, the
// Python object would live forever. So every owned proxy is registered here
// (with the address of its Python object): when JavaScript's garbage collector
// has freed the proxy (nobody can reach it any more), the browser calls this
// function some time later, and it releases the reference (Py_DECREF).
// "Backstop": a safety net, not the plan. When (and whether) the garbage
// collector runs is up to the browser, and it does not know how big the
// Python object behind a small proxy is. destroy() unregisters the proxy, so
// the reference is never released twice. (PythonError objects use the same
// registry for the exception they hold.)
const registry = new FinalizationRegistry((ptr: number) => {
  ownedProxies -= 1;
  release(ptr);
});

// for tests: the number of owned PyProxies that hold a reference right now
// (created, and neither destroyed nor collected)
let ownedProxies = 0;

/** for tests: see `ownedProxies` */
export function ownedProxyCount(): number {
  return ownedProxies;
}

/** a Python exception that reached JavaScript */
export class PythonError extends Error {
  /** the name of the type of the Python exception, e.g. "KeyError" */
  type: string;
  /**
   * The Python exception object itself, as address. This error owns one
   * reference to it (released when the error is garbage collected). It is
   * what lets Python raise the original exception again if this error
   * travels back into Python (see `fail` in jsops.ts).
   */
  __pyjs_exception: number;

  /**
   * `message`: the formatted Python traceback. `exception`: the address of
   * the Python exception. pyjs always passes it; the class is public (for
   * `instanceof`), so user code can construct one too, without: such an
   * error stands for no Python exception (0) and is an ordinary JavaScript
   * error when it reaches Python.
   */
  constructor(type: string, message: string, exception?: number) {
    super(message);
    this.name = "PythonError";
    this.type = type;
    this.__pyjs_exception = typeof exception === "number" ? exception : 0;
    if (this.__pyjs_exception !== 0) {
      errorRegistry.register(this, this.__pyjs_exception);
    }
  }
}

// releases the Python exception of a PythonError that was garbage collected
// (the same backstop as `registry` for proxies)
const errorRegistry = new FinalizationRegistry((exception: number) => release(exception));

/**
 * The JS error for a Python exception. When a call into Python raised, the C
 * side (write_error in src/py_entry.cpp) does not write one result slot but
 * three, one after the other (a slot is 16 bytes):
 *
 *     at p        the exception itself (its address)
 *     at p + 16   a string: the formatted traceback
 *     at p + 32   a string: the name of the exception type, e.g. "KeyError"
 */
function decodeError(p: number): PythonError {
  const exception = slotNum(p);
  const message = slotString(p + 16);
  const type = slotString(p + 32);
  return new PythonError(type, message, exception);
}

function alive(state: State): number {
  if (state.ptr === 0) {
    throw new Error(state.destroyed);
  }
  return state.ptr;
}

/**
 * Call the Python object of `state`: obj(*args, **kwargs). Internal, not
 * for users: the user calls the proxy (`proxy(1, 2)`, the `apply` trap of
 * the handler) or `proxy.callKwargs(...)`, and those call this with the
 * proxy's State (see State).
 *
 * The steps: the arguments are written into slots (encode: in the scratch
 * region, or malloc'ed if they do not fit), ONE call of the wasm export
 * pyjs_call (src/py_entry.cpp) runs the Python call, the result slot is
 * decoded (or the exception thrown as PythonError).
 */
function callPython(state: State, args: ArrayLike<any>, kwargs: any): any {
  const ptr = alive(state);
  const npos = args.length;
  const names = kwargs === undefined ? null : Object.keys(kwargs);
  const nkw = names === null ? 0 : names.length;
  const n = npos + 2 * nkw;
  const mark = scratchMark();
  let slots = scratchSlots(n);
  const big = slots === 0;
  if (big) {
    slots = alloc(16 * n);
  }
  // a synchronous entry: the Python code cannot suspend (JSPI)
  const couldSuspend = jspi.canSuspend;
  jspi.canSuspend = false;
  jspi.depth += 1;
  let rc;
  // how many slots are encoded: if a later argument cannot be encoded (a
  // destroyed proxy), what the earlier ones own is given back
  let encoded = 0;
  try {
    for (; encoded < npos; encoded++) {
      encode(args[encoded], slots + 16 * encoded, true);
    }
    for (let i = 0; i < nkw; i++) {
      // (names behind the values: encoded only counts the complete front)
      encode(names![i], slots + 16 * (npos + nkw + i), true);
      encode(kwargs[names![i]], slots + 16 * (npos + i), true);
      encoded += 1;
    }
    encoded = -1; // all of them: the C side takes over
    rc = pyCall(ptr, slots, npos, nkw, result);
  } catch (error) {
    if (encoded >= 0) {
      discardSlots(slots, encoded);
    }
    throw error;
  } finally {
    jspi.depth -= 1;
    jspi.canSuspend = couldSuspend;
    scratchRelease(mark);
    if (big) {
      _free(slots);
    }
  }
  if (rc !== Rc.OK) {
    throw decodeError(result);
  }
  return decode(result, true);
}

/** a promise that resolves in a later macrotask (after the JS stack unwound) */
function nextMacrotask(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

/**
 * obj(*args) where the Python code may suspend (run_sync): returns a promise.
 * Without JSPI: a plain call. Each such call is a "task" (see jspi.ts): any
 * number of them can be suspended at the same time.
 *
 * A task is only entered at the event loop level, with no wasm code running:
 * that is what lets stack_state.ts place its C stack data freely (the data of
 * running wasm frames could not be moved). If wasm code is running (JS that
 * Python called calls this), the call waits for the next macrotask first, so
 * it behaves like "start this on the event loop" (as in pyodide).
 *
 * Internal like callPython: users call `proxy.callPromising(...args)` (a
 * method of the proxy), which passes the proxy's State; nobody passes a
 * State by hand.
 */
async function callPythonPromising(state: State, args: ArrayLike<any>): Promise<any> {
  if (pyCallPromising === null || jspi.disabled) {
    return callPython(state, args, undefined);
  }
  // The object must survive until the call is over, even if the proxy is
  // destroyed meanwhile (e.g. while waiting for the macrotask).
  const ptr = alive(state);
  pyIncref(ptr);
  let slots = 0;
  // copies of argument proxies made for the wait, see below
  let copies: any[] | null = null;
  try {
    if (jspi.depth > 0) {
      // Python arguments of the JavaScript function that calls us are
      // "borrowed" proxies: gone when that function returns, which is
      // before this call starts. They are arguments of THIS call now, so
      // each gets a proxy of its own for as long as this call takes.
      copies = [];
      args = Array.from(args, (arg) => ownedCopyOfBorrowed(arg, copies!));
      await nextMacrotask();
    }
    const npos = args.length;
    // the slots must outlive this function's synchronous part: not in the
    // scratch region. `out`: 4 slots, see pyjs_call_promising.
    slots = alloc(16 * npos + 64);
    const out = slots + 16 * npos;
    const mark = scratchMark();
    let promise;
    let encoded = 0;
    try {
      for (; encoded < npos; encoded++) {
        encode(args[encoded], slots + 16 * encoded, true);
      }
      encoded = -1;
      // Where the task's C stack goes (stack_state.ts). From here on until
      // the wasm export runs, nothing may use the C stack.
      enterTask();
      // Undone by the task itself when it suspends (jspiAwait) / finishes
      // (taskDone, called at the end of pyjs_call_promising), redone when it
      // resumes (jspiResume).
      jspi.canSuspend = true;
      jspi.depth += 1;
      // (the arguments are converted before Python runs: the strings in the
      // scratch region are not needed after this call returned its promise)
      promise = pyCallPromising(ptr, slots, npos, 0, out);
    } catch (error) {
      if (encoded >= 0) {
        // an argument could not be encoded: nothing was entered
        discardSlots(slots, encoded);
      } else {
        // calling the export itself failed: we are at the event loop level
        // (see above), where nothing is entered
        jspi.depth = 0;
        jspi.canSuspend = false;
      }
      throw error;
    } finally {
      scratchRelease(mark);
    }
    let rc;
    try {
      rc = await promise;
    } catch (error) {
      // the wasm code failed (a trap): taskDone was not called
      jspi.depth = 0;
      jspi.canSuspend = false;
      throw error;
    }
    if (rc === Rc.NOT_ENTERED) {
      // the task never ran, so it could not undo the bookkeeping of above
      taskDone();
    }
    // out[3]: what keeps the result alive until it is decoded
    const keep = slotNum(out + 48);
    try {
      if (rc !== Rc.OK) {
        throw decodeError(out);
      }
      return decode(out, true);
    } finally {
      if (keep !== 0) {
        release(keep);
      }
    }
  } finally {
    if (slots !== 0) {
      _free(slots);
    }
    if (copies !== null) {
      destroyBorrowed(copies);
    }
    release(ptr);
  }
}

/**
 * For callPythonPromising: `arg` itself, or, if it is a borrowed PyProxy (an
 * argument of the JavaScript function calling us, destroyed when that
 * returns), an owned proxy of the same Python object, also appended to
 * `copies` (which the caller destroys when its call is over).
 */
function ownedCopyOfBorrowed(arg: any, copies: any[]): any {
  if (arg === null || (typeof arg !== "object" && typeof arg !== "function")) {
    return arg;
  }
  const state: State | undefined = arg[PYPROXY];
  if (state === undefined || state.owned) {
    return arg;
  }
  const ptr = alive(state);
  pyIncref(ptr);
  const copy = create(ptr, state.flags, true);
  copies.push(copy);
  return copy;
}

/**
 * Py_DECREF, as an entry into Python of its own: releasing the last
 * reference of an object runs Python code (`__del__`, weakref callbacks),
 * which can call JavaScript, which can call Python again. So it is counted
 * like every other synchronous entry (see jspi.ts): code running in it
 * cannot suspend, and a `callPromising` made from it waits for it to end.
 */
function release(ptr: number): void {
  const couldSuspend = jspi.canSuspend;
  jspi.canSuspend = false;
  jspi.depth += 1;
  try {
    pyDecref(ptr);
  } finally {
    jspi.depth -= 1;
    jspi.canSuspend = couldSuspend;
  }
}

/**
 * Called by pyjs_call_promising (src/py_entry.cpp) when the task's Python
 * call returned, right before the export returns: the task is no longer an
 * active entry (see callPythonPromising).
 */
export function taskDone(): void {
  jspi.depth -= 1;
  jspi.canSuspend = false;
}

/**
 * Do the operation `op` (one of PyOp: getattr, setitem, len, ...; see the
 * table there) on the Python object of `state`, with `nargs` (0..2)
 * arguments `a`, `b`: they are written into slots, ONE call of the wasm
 * export pyjs_op (src/py_entry.cpp) does the operation in Python. Returns the
 * return code (Rc); the value is left in the result slots (`value` below
 * decodes it). A Python exception is thrown as PythonError.
 *
 * Used by the traps of the handler and the methods of the proxy, e.g.
 * `proxy.has(k)` is operate(PyOp.CONTAINS, state, 1, k).
 */
function operate(op: PyOp, state: State, nargs: number, a?: any, b?: any): number {
  const ptr = alive(state);
  const mark = scratchMark();
  let slots = scratchSlots(2);
  const big = slots === 0;
  if (big) {
    slots = alloc(32);
  }
  const couldSuspend = jspi.canSuspend;
  jspi.canSuspend = false;
  jspi.depth += 1;
  let rc;
  try {
    if (nargs > 0) {
      encode(a, slots, true);
    }
    if (nargs > 1) {
      encode(b, slots + 16, true);
    }
    rc = pyOp(op, ptr, slots, result);
  } finally {
    jspi.depth -= 1;
    jspi.canSuspend = couldSuspend;
    scratchRelease(mark);
    if (big) {
      _free(slots);
    }
  }
  if (rc === Rc.ERROR) {
    throw decodeError(result);
  }
  return rc;
}

/** the value of an operation */
function value(op: PyOp, state: State, nargs: number, a?: any, b?: any): any {
  operate(op, state, nargs, a, b);
  return decode(result, true);
}

/**
 * Destroy ONE PyProxy (the one this State belongs to): it gives up its
 * reference to the Python object (Py_DECREF), and the proxy becomes unusable
 * (every later use throws state.destroyed). The Python object itself is only
 * freed if nothing else in Python still references it.
 *
 * Called by `proxy.destroy()`, for borrowed proxies at the end of the call
 * (destroyBorrowed), and for the temporary iterator of a `for ... of` loop.
 */
function destroy(state: State): void {
  if (state.ptr !== 0) {
    if (state.owned) {
      registry.unregister(state);
      ownedProxies -= 1;
    }
    const ptr = state.ptr;
    state.ptr = 0;
    release(ptr);
  }
}

/**
 * A JavaScript promise for an awaitable Python object (a coroutine, a
 * task, a future: anything Python can `await`). It resolves with what
 * awaiting the object in Python gives, or rejects with its exception (as
 * PythonError). Python runs the awaitable as an asyncio task; this only
 * connects its outcome to a promise. One promise per proxy, created on first
 * use (awaiting a coroutine twice is not possible in Python either).
 */
function promiseOf(proxy: any): Promise<any> {
  const state: State = proxy[PYPROXY];
  return (state.promise ??= new Promise((resolve, reject) => {
    // python: pyjs.core._then(awaitable, settle). When the awaitable is
    // done, python calls `settle` with a function `get` that returns the
    // result or raises the exception of the awaitable. Calling it here
    // turns both into what a promise needs with the ordinary machinery of
    // calls into python: a result arrives as value (a Python object as
    // PyProxy owned by the receiver), an exception is thrown as PythonError.
    thenHelper(proxy, (get: () => any) => {
      try {
        resolve(get());
      } catch (error) {
        reject(error);
      }
    });
  }));
}

// What makes the proxy of an awaitable Python object usable like a promise.
//
// JavaScript's `await x` (and Promise.resolve(x), Promise.all, ...) treat
// anything with a `then(onFulfilled, onRejected)` method as a promise (a
// "thenable"). So the proxies of awaitable Python objects (PyFlag.AWAITABLE)
// get these three methods (found by the `get` trap of the handler), each
// forwarding to the real promise of promiseOf. Then
//     const result = await pyproxy_of_a_coroutine;
// works in JavaScript like awaiting a promise.
const promiseMembers: Record<string, any> = {
  then(this: any, onFulfilled?: any, onRejected?: any): Promise<any> {
    return promiseOf(this).then(onFulfilled, onRejected);
  },
  catch(this: any, onRejected?: any): Promise<any> {
    return promiseOf(this).catch(onRejected);
  },
  finally(this: any, onFinally?: any): Promise<any> {
    return promiseOf(this).finally(onFinally);
  },
};

/**
 * Destroy the "borrowed" proxies of one call (see "Borrowed" proxies in
 * codec.ts).
 *
 * Borrowed are exactly the proxies created automatically when Python
 * passes Python objects to JavaScript, i.e. the arguments of a call from
 * Python into JS (`js_function(some_list)`), the value of `obj.x = some_list`,
 * and so on. JavaScript did not ask for them and does not own them, so they
 * are destroyed automatically when that call / operation is over (jsops.ts
 * calls this; for a call that returned a promise: once it settled). A
 * PyProxy JavaScript may keep has to be made explicitly with create_proxy
 * (owned, destroyed by its user).
 */
export function destroyBorrowed(proxies: any[]): void {
  for (let i = 0; i < proxies.length; i++) {
    destroy(proxies[i][PYPROXY]);
  }
}

/**
 * A JS iterator over a Python iterator: what `for (const x of proxy)` uses.
 *
 * `proxy` is the PyProxy of the Python iterator that iter(obj) returned
 * (made by the Symbol.iterator method of the proxy of `obj`).
 * Each step calls next() in Python; when the Python iterator is exhausted
 * (StopIteration: Rc.STOP), the loop ends. The iterator proxy is destroyed
 * at the end, also when the loop is left early (`break`: `finally`).
 */
function* iterate(proxy: any): Generator<any> {
  // `proxy` itself must stay referenced for the whole loop, not only its
  // State: an owned proxy nobody refers to any more is collected by
  // JavaScript's garbage collector, and the registry then releases the
  // Python iterator while the loop still uses it. The `finally` below uses
  // `proxy`, which keeps it alive until the loop is over.
  const iterator: State = proxy[PYPROXY];
  try {
    while (operate(PyOp.NEXT, iterator, 0) !== Rc.STOP) {
      yield decode(result, true);
    }
  } finally {
    destroy(proxy[PYPROXY]);
  }
}

function returnThis(this: any): any {
  return this;
}

/**
 * The methods of a JS generator, for the proxy of a Python generator:
 * next(value) (python's send), throw(error), return(value) (python's close),
 * each giving a step {done, value}. Done by the python helper
 * pyjs.core._generator_step.
 */
const generatorMethods: Record<string, (this: any, arg?: any) => any> = {
  next(arg) {
    return generatorStepHelper(this, "next", arg);
  },
  throw(arg) {
    return generatorStepHelper(this, "throw", arg);
  },
  return(arg) {
    return generatorStepHelper(this, "return", arg);
  },
};

/** `next()` of the proxy of a Python iterator: a JS iterator step */
function iteratorNext(this: any): { done: boolean; value: any } {
  if (operate(PyOp.NEXT, this[PYPROXY], 0) === Rc.STOP) {
    return { done: true, value: undefined };
  }
  return { done: false, value: decode(result, true) };
}

// The members of every PyProxy (they win over Python attributes of the same
// name). Called as methods: `this` is the proxy.
const members: Record<string | symbol, any> = Object.assign(Object.create(null), {
  /** release the Python object: the proxy is unusable afterwards */
  destroy(this: any): void {
    destroy(this[PYPROXY]);
  },
  /** another proxy of the same object, with its own lifetime */
  copy(this: any): any {
    const state: State = this[PYPROXY];
    pyIncref(alive(state));
    return create(state.ptr, state.flags, true);
  },
  toString(this: any): string {
    return value(PyOp.STR, this[PYPROXY], 0);
  },
  /** obj[key], obj[key0, key1, ...] */
  get(this: any, ...keys: any[]): any {
    return value(PyOp.GETITEM, this[PYPROXY], 1, keys.length === 1 ? keys[0] : keys);
  },
  set(this: any, key: any, item: any): void {
    operate(PyOp.SETITEM, this[PYPROXY], 2, key, item);
  },
  has(this: any, key: any): boolean {
    return value(PyOp.CONTAINS, this[PYPROXY], 1, key);
  },
  /** `del obj[key]` */
  delete(this: any, key: any): void {
    operate(PyOp.DELITEM, this[PYPROXY], 1, key);
  },
  /**
   * obj(*args, **kwargs). JavaScript has no keyword arguments, so they are
   * passed as one object, which must be the LAST argument:
   * `f.callKwargs(1, 2, {sep: "-"})` is python's `f(1, 2, sep="-")`.
   */
  callKwargs(this: any, ...args: any[]): any {
    if (args.length === 0) {
      throw new TypeError("callKwargs requires at least one argument (the object with the keyword arguments)");
    }
    const kwargs = args.pop();
    // (a plain object: not a PyProxy, not an Array, not null)
    if (
      kwargs === null ||
      typeof kwargs !== "object" ||
      Array.isArray(kwargs) ||
      kwargs[PYPROXY] !== undefined
    ) {
      throw new TypeError("callKwargs: the last argument must be an object with the keyword arguments");
    }
    return callPython(this[PYPROXY], args, kwargs);
  },
  /** obj(*args), returns a promise: the Python code may use run_sync (JSPI) */
  callPromising(this: any, ...args: any[]): Promise<any> {
    return callPythonPromising(this[PYPROXY], args);
  },
  /**
   * A deep copy of the Python object as JS value (python's `pyjs.to_js`):
   * list -> Array, dict -> Object, ... `options` are the keyword arguments
   * of `to_js`, e.g. {depth: 1}.
   */
  toJs(this: any, options?: any): any {
    return options === undefined ? toJsHelper(this) : toJsHelper.callKwargs(this, options);
  },
  [Symbol.iterator](this: any): Iterator<any> {
    // (the proxy of the Python iterator, not just its State: see iterate)
    return iterate(value(PyOp.ITER, this[PYPROXY], 0));
  },
  [Symbol.toPrimitive](this: any, hint: string): any {
    const str = value(PyOp.STR, this[PYPROXY], 0);
    return hint === "number" ? Number(str) : str;
  },
});

/**
 * The handler of every PyProxy (see "WHAT AN ES PROXY IS" at the top of this
 * file).
 *
 * A "proxy handler" is the plain object given to `new Proxy(target,
 * handler)`. Its functions ("traps") are what JavaScript calls INSTEAD of
 * the normal behaviour when code operates on the proxy:
 *   get(target, property)            proxy.property, proxy[property]
 *   set(target, property, value)     proxy.property = value
 *   has(target, property)            property in proxy
 *   deleteProperty(target, property) delete proxy.property
 *   apply(target, thisArg, args)     proxy(...args)
 * (`target` is the object the proxy wraps: here a small object / function
 * carrying the State of this proxy, see `create`.) One handler serves all
 * PyProxies: everything specific to one proxy is in its State.
 */
const handler: ProxyHandler<any> = {
  get(target, property) {
    if (property === PYPROXY) {
      return target.state;
    }
    const state: State = target.state;
    if (property === Symbol.iterator) {
      // only iterable Python objects are iterable in JS (code like
      // Array.from / spread probes for this property); a Python iterator
      // without __iter__ is its own iterator, as in JS
      if (state.flags & PyFlag.ITERABLE) {
        return members[property];
      }
      return state.flags & PyFlag.ITERATOR ? returnThis : undefined;
    }
    const member = members[property];
    if (member !== undefined) {
      return member;
    }
    if (typeof property === "symbol") {
      // (a callable's ES Proxy target is a function: the symbols of
      // functions, e.g. Symbol.hasInstance)
      return state.flags & PyFlag.CALLABLE ? Reflect.get(target, property) : undefined;
    }
    // (a generator first: it is an iterator too, but its `next` sends a
    // value and reports the return value at the end)
    if (state.flags & PyFlag.GENERATOR && (property === "next" || property === "throw" || property === "return")) {
      return generatorMethods[property];
    }
    if (property === "next" && state.flags & PyFlag.ITERATOR) {
      return iteratorNext;
    }
    switch (property) {
      case "type":
        return value(PyOp.TYPE, state, 0);
      case "length":
        // len(obj) for objects that have one; for others `length` is an
        // ordinary attribute
        if (state.flags & PyFlag.SIZED) {
          return value(PyOp.LEN, state, 0);
        }
        break;
      case "call":
      case "apply":
      case "bind":
        if (state.flags & PyFlag.CALLABLE) {
          return (Function.prototype as any)[property];
        }
        break;
      case "then":
      case "catch":
      case "finally":
        // `await` / Promise.resolve probe every value for `then`: only an
        // awaitable Python object is a thenable
        if (state.flags & PyFlag.AWAITABLE) {
          return promiseMembers[property];
        }
        if (property === "then") {
          return undefined;
        }
    }
    // a missing attribute is undefined, as for JS objects
    if (operate(PyOp.GETATTR, state, 1, property) === Rc.NO_ATTR) {
      return undefined;
    }
    return decode(result, true);
  },
  set(target, property, item) {
    if (typeof property === "symbol") {
      return false;
    }
    if (property === "length" && target.state.flags & PyFlag.SIZED) {
      // (`length` is len(obj) there, see `get`)
      throw new TypeError("cannot set the length of a Python object");
    }
    operate(PyOp.SETATTR, target.state, 2, property, item);
    return true;
  },
  // `property in proxy`: the same answers as `get` gives values
  has(target, property) {
    const flags = target.state.flags;
    if (property === Symbol.iterator) {
      return (flags & (PyFlag.ITERABLE | PyFlag.ITERATOR)) !== 0;
    }
    if (property === PYPROXY || property in members) {
      return true;
    }
    if (typeof property === "symbol" || (property === "prototype" && flags & PyFlag.CALLABLE)) {
      // (see `get`; JS also requires `true` for the fixed properties of
      // the target function)
      return flags & PyFlag.CALLABLE ? Reflect.has(target, property) : false;
    }
    if (property === "next" && flags & PyFlag.ITERATOR) {
      return true;
    }
    if ((property === "throw" || property === "return") && flags & PyFlag.GENERATOR) {
      return true;
    }
    switch (property) {
      case "type":
        return true;
      case "length":
        if (flags & PyFlag.SIZED) {
          return true;
        }
        break;
      case "call":
      case "apply":
      case "bind":
        if (flags & PyFlag.CALLABLE) {
          return true;
        }
        break;
      case "then":
      case "catch":
      case "finally":
        if (flags & PyFlag.AWAITABLE) {
          return true;
        }
        if (property === "then") {
          return false;
        }
    }
    // (not GETATTR: that hands over the attribute's value, a reference
    // somebody would have to give back; this only answers yes / no)
    operate(PyOp.HASATTR, target.state, 1, property);
    return decode(result, true) === true;
  },
  deleteProperty(target, property) {
    if (typeof property === "symbol") {
      return false;
    }
    const descriptor = Reflect.getOwnPropertyDescriptor(target, property);
    if (descriptor !== undefined && !descriptor.configurable) {
      // a fixed property of the target function (`prototype`): JS forbids
      // deleting it, the Python attribute stays too
      throw new TypeError(`Cannot delete property '${property}'`);
    }
    if (property === "length" && target.state.flags & PyFlag.SIZED) {
      // (`length` is len(obj), see `get`: nothing to delete)
      return true;
    }
    operate(PyOp.DELATTR, target.state, 1, property);
    return true;
  },
  apply(target, _thisArg, args) {
    return callPython(target.state, args, undefined);
  },
  // `new proxy(...args)`: for a Python class that is calling it (Python has
  // no `new`). Without this trap JavaScript would run the target function
  // itself as constructor: an empty object, and Python never called.
  construct(target, args) {
    const instance = callPython(target.state, args, undefined);
    if (instance === null || (typeof instance !== "object" && typeof instance !== "function")) {
      // (JavaScript requires an object as result of `new`)
      throw new TypeError("new: the Python callable returned a value that is no object in JavaScript");
    }
    return instance;
  },
};

/**
 * The target of the ES Proxy (see the top of this file) of a callable
 * Python object.
 *
 * Why a function: JavaScript only lets a Proxy be called (`proxy(1, 2)`,
 * which runs the `apply` trap) if its target is itself a function. For a
 * Python object that is not callable the target is a plain object instead
 * (`{ state }` in `create`), so `typeof proxy` is "object" and calling it is
 * a TypeError, as for any non-function in JavaScript.
 */
function callableTarget(state: State): any {
  // A plain function (not an arrow function): with a `prototype`, like
  // every JS function that can be used as class (pyodide does the same).
  return withState(function () {}, state);
}

/**
 * Store the State of a proxy on its target, as property `state` that does not
 * show: not enumerable, so that Object.keys(proxy), JSON.stringify(proxy) and
 * `{...proxy}` do not list it (they would also ask Python for an attribute
 * `state`). Configurable and writable: only then may the `get` trap answer
 * `proxy.state` with the Python attribute of that name (JavaScript checks
 * that a proxy does not lie about fixed properties of its target).
 */
function withState(target: any, state: State): any {
  Object.defineProperty(target, "state", { value: state, enumerable: false, configurable: true, writable: true });
  return target;
}

/** a PyProxy for the Python object `ptr` (the proxy owns a reference) */
function create(ptr: number, flags: number, owned: boolean): any {
  const state: State = { ptr, flags, owned, destroyed: owned ? DESTROYED_MESSAGE : BORROWED_DESTROYED_MESSAGE };
  const proxy = new Proxy(flags & PyFlag.CALLABLE ? callableTarget(state) : withState({}, state), handler);
  if (owned) {
    registry.register(proxy, ptr, state);
    ownedProxies += 1;
  }
  return proxy;
}

setPyProxyFactory(create);

/**
 * The JS error for a Python exception object (`proxy`: its PyProxy), as if
 * the exception had just been raised by a call into Python. Used to throw a
 * Python exception into JS code (generator.throw): when such an error
 * comes back to Python uncaught, the original exception is raised again
 * (see `fail` in jsops.ts).
 */
export function pythonErrorFor(proxy: any): PythonError {
  const state: State = proxy[PYPROXY];
  const ptr = alive(state);
  const type = value(PyOp.TYPE, state, 0);
  // (the repr as message: "ValueError('bad value')")
  const message = value(PyOp.REPR, state, 0);
  // the error owns a reference to the exception (see PythonError)
  pyIncref(ptr);
  return new PythonError(type, message, ptr);
}

/** `import name` */
export function pyimport(name: string): any {
  const mark = scratchMark();
  let slot = scratchSlots(1);
  const big = slot === 0;
  if (big) {
    slot = alloc(16);
  }
  // a synchronous entry like every other (see callPython)
  const couldSuspend = jspi.canSuspend;
  jspi.canSuspend = false;
  jspi.depth += 1;
  let rc;
  try {
    encode(name, slot, true);
    rc = pyOp(PyOp.IMPORT, 0, slot, result);
  } finally {
    jspi.depth -= 1;
    jspi.canSuspend = couldSuspend;
    scratchRelease(mark);
    if (big) {
      _free(slot);
    }
  }
  if (rc !== Rc.OK) {
    throw decodeError(result);
  }
  return decode(result, true);
}
