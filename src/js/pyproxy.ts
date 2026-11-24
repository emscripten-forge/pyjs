// PyProxy: a JavaScript object standing for a Python object. An ES Proxy:
// property access goes to the Python attributes, a callable Python object is
// callable. Every operation is one JS -> wasm call of an export of
// src/py_entry.cpp, arguments and result travel as slots (codec.ts).
import { jspi } from "./jspi";
import {
  PyFlag,
  PYPROXY,
  decode,
  encode,
  scratchMark,
  scratchRelease,
  scratchSlots,
  setPyProxyFactory,
  slotNum,
  slotString,
} from "./codec";

/** operations of the export pyjs_op (PyOp in src/py_entry.cpp) */
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
}

/** return codes of the exports */
const enum Rc {
  OK = 0,
  ERROR = 1,
  NO_ATTR = 2,
  STOP = 5,
}

interface State {
  ptr: number; // PyObject*, 0 once destroyed
  flags: number; // PyFlag
  owned: boolean; // registered for finalization
  destroyed: string; // the message of the error for a use after destroy()
  promise?: Promise<any>; // of an awaitable, once it was awaited from JS
}

const DESTROYED = "This proxy was destroyed: the Python object is no longer accessible.";
const BORROWED_DESTROYED =
  "This borrowed proxy was automatically destroyed at the end of a function call. " +
  "Try using create_proxy or create_once_callable.";

// the exports, the result slots (3: an error is 3 slots)
let pyCall: (fn: number, args: number, npos: number, nkw: number, out: number) => number;
let pyOp: (op: number, obj: number, args: number, out: number) => number;
let pyDecref: (obj: number) => void;
let pyIncref: (obj: number) => void;
// (JSPI: the call may suspend, so it returns a promise)
let pyCallPromising: ((fn: number, args: number, npos: number, nkw: number, out: number) => Promise<number>) | null =
  null;
let result = 0;

// python helper `(awaitable, resolve, reject)`: settles a promise with the
// result of an awaitable (set by the runtime once python runs)
let thenHelper: any = null;

// python `to_js`
let toJsHelper: any = null;

/** the python helpers of PyProxy.then / PyProxy.toJs */
export function setPythonHelpers(then: any, toJs: any): void {
  thenHelper = then;
  toJsHelper = toJs;
}

/** bind the wasm exports (once the wasm module is instantiated) */
export function initPyProxy(): void {
  pyCall = wasmExports.pyjs_call;
  pyOp = wasmExports.pyjs_op;
  pyDecref = wasmExports.pyjs_decref;
  pyIncref = wasmExports.pyjs_incref;
  if (jspi.supported) {
    pyCallPromising = (WebAssembly as any).promising(wasmExports.pyjs_call_promising);
  }
  result = _malloc(3 * 16);
}

// the backstop for proxies nobody destroyed
const registry = new FinalizationRegistry((ptr: number) => {
  pyDecref(ptr);
});

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

  /** `message`: the formatted Python traceback */
  constructor(type: string, message: string, exception: number) {
    super(message);
    this.name = "PythonError";
    this.type = type;
    this.__pyjs_exception = exception;
    registry.register(this, exception);
  }
}

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

/** obj(*args, **kwargs) */
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
    slots = _malloc(16 * n);
  }
  // a synchronous entry: the Python code cannot suspend (JSPI)
  const couldSuspend = jspi.canSuspend;
  jspi.canSuspend = false;
  jspi.depth += 1;
  let rc;
  try {
    for (let i = 0; i < npos; i++) {
      encode(args[i], slots + 16 * i, true);
    }
    for (let i = 0; i < nkw; i++) {
      encode(kwargs[names![i]], slots + 16 * (npos + i), true);
      encode(names![i], slots + 16 * (npos + nkw + i), true);
    }
    rc = pyCall(ptr, slots, npos, nkw, result);
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

/**
 * obj(*args) where the Python code may suspend (run_sync): returns a promise.
 * Without JSPI, or when called from JS that Python called (no stack
 * switching possible there): a plain call.
 */
async function callPythonPromising(state: State, args: ArrayLike<any>): Promise<any> {
  if (pyCallPromising === null || jspi.disabled || jspi.depth > 0) {
    return callPython(state, args, undefined);
  }
  const ptr = alive(state);
  const npos = args.length;
  // the slots must outlive this function's synchronous part: not in the scratch region
  const slots = _malloc(16 * npos + 48);
  const out = slots + 16 * npos;
  const mark = scratchMark();
  const couldSuspend = jspi.canSuspend;
  jspi.canSuspend = true;
  jspi.depth += 1;
  let promise;
  try {
    for (let i = 0; i < npos; i++) {
      encode(args[i], slots + 16 * i, true);
    }
    // (the arguments are converted before Python runs: the strings in the
    // scratch region are not needed after this call returned its promise)
    promise = pyCallPromising(ptr, slots, npos, 0, out);
  } catch (error) {
    jspi.depth -= 1;
    _free(slots);
    throw error;
  } finally {
    jspi.canSuspend = couldSuspend;
    scratchRelease(mark);
  }
  try {
    const rc = await promise;
    if (rc !== Rc.OK) {
      throw decodeError(out);
    }
    return decode(out, true);
  } finally {
    jspi.depth -= 1;
    _free(slots);
  }
}

/** an operation with up to two arguments; returns the return code */
function operate(op: PyOp, state: State, nargs: number, a?: any, b?: any): number {
  const ptr = alive(state);
  const mark = scratchMark();
  let slots = scratchSlots(2);
  const big = slots === 0;
  if (big) {
    slots = _malloc(32);
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

function destroy(state: State): void {
  if (state.ptr !== 0) {
    if (state.owned) {
      registry.unregister(state);
    }
    const ptr = state.ptr;
    state.ptr = 0;
    // (releasing the object can run Python code: __del__)
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
}

/** the promise of an awaitable Python object (one per proxy) */
function promiseOf(proxy: any): Promise<any> {
  const state: State = proxy[PYPROXY];
  return (state.promise ??= new Promise((resolve, reject) => {
    // python: pyjs.core._then(awaitable, resolve, reject)
    thenHelper(proxy, resolve, reject);
  }));
}

// what makes an awaitable Python object a thenable
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

/** destroy the proxies created for the arguments of a call from Python */
export function destroyBorrowed(proxies: any[]): void {
  for (let i = 0; i < proxies.length; i++) {
    destroy(proxies[i][PYPROXY]);
  }
}

/** a JS iterator over a Python iterator */
function* iterate(iterator: State): Generator<any> {
  try {
    while (operate(PyOp.NEXT, iterator, 0) !== Rc.STOP) {
      yield decode(result, true);
    }
  } finally {
    destroy(iterator);
  }
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
    const kwargs = args.pop();
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
    const iterator = value(PyOp.ITER, this[PYPROXY], 0);
    return iterate(iterator[PYPROXY]);
  },
  [Symbol.toPrimitive](this: any, hint: string): any {
    const str = value(PyOp.STR, this[PYPROXY], 0);
    return hint === "number" ? Number(str) : str;
  },
});

const handler: ProxyHandler<any> = {
  get(target, property) {
    if (property === PYPROXY) {
      return target.state;
    }
    const member = members[property];
    if (member !== undefined) {
      return member;
    }
    const state: State = target.state;
    if (typeof property === "symbol") {
      return undefined;
    }
    switch (property) {
      case "type":
        return value(PyOp.TYPE, state, 0);
      case "length":
        return value(PyOp.LEN, state, 0);
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
    operate(PyOp.SETATTR, target.state, 2, property, item);
    return true;
  },
  has(target, property) {
    if (property === PYPROXY || property in members) {
      return true;
    }
    if (typeof property === "symbol") {
      return false;
    }
    return operate(PyOp.GETATTR, target.state, 1, property) !== Rc.NO_ATTR;
  },
  deleteProperty(target, property) {
    if (typeof property === "symbol") {
      return false;
    }
    operate(PyOp.DELATTR, target.state, 1, property);
    return true;
  },
  apply(target, _thisArg, args) {
    return callPython(target.state, args, undefined);
  },
};

/** the target of the ES Proxy of a callable (only functions can be called) */
function callableTarget(state: State): any {
  const target: any = function () {};
  target.state = state;
  return target;
}

/** a PyProxy for the Python object `ptr` (the proxy owns a reference) */
function create(ptr: number, flags: number, owned: boolean): any {
  const state: State = { ptr, flags, owned, destroyed: owned ? DESTROYED : BORROWED_DESTROYED };
  const proxy = new Proxy(flags & PyFlag.CALLABLE ? callableTarget(state) : { state }, handler);
  if (owned) {
    registry.register(proxy, ptr, state);
  }
  return proxy;
}

setPyProxyFactory(create);

/** `import name` */
export function pyimport(name: string): any {
  const mark = scratchMark();
  const slot = scratchSlots(1);
  let rc;
  try {
    encode(name, slot, true);
    rc = pyOp(PyOp.IMPORT, 0, slot, result);
  } finally {
    scratchRelease(mark);
  }
  if (rc !== Rc.OK) {
    throw decodeError(result);
  }
  return decode(result, true);
}
