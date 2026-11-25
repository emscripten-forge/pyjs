// Python -> JavaScript: what the EM_JS functions of src/js_proxy.cpp /
// src/module.cpp call (a JSProxy operating on its JS object). Arguments
// arrive as slots, the result is written into a slot (codec.ts); nothing
// throws: errors are a return code + the thrown value in the result slot.
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
import { fromStream, toStream } from "./deep";
import { jspi } from "./jspi";
import { PythonError, destroyBorrowed } from "./pyproxy";

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

// destroys the argument proxies of a generator once it is garbage collected
const generatorArguments = new FinalizationRegistry((proxies: any[]) => destroyBorrowed(proxies));

/**
 * the proxies created for the arguments of a call are destroyed after it; if
 * it returned a promise: when that settles; a generator: with the generator
 */
function releaseBorrowed(proxies: any[], result: any): void {
  if (isGenerator(result)) {
    // A generator function was called: its body runs later, step by step,
    // and uses the arguments then. They live as long as the generator
    // (destroyed when the garbage collector frees it).
    generatorArguments.register(result, proxies);
    return;
  }
  if (isThenable(result)) {
    // Not right when the promise settles but one step later
    // (queueMicrotask). The promise may settle WITH one of the proxies
    // (`async (x) => x`): whoever awaits it (python) is notified in the
    // same round as this callback and must still find the proxy alive to
    // get the Python object out of it.
    const release = () => queueMicrotask(() => destroyBorrowed(proxies));
    result.then(release, release);
  } else {
    destroyBorrowed(proxies);
  }
}

/**
 * fn(...args) with `this` = self (handle or 0), or new fn(...args): `args`
 * points to npos + nkw value slots followed by nkw name slots; keyword
 * arguments become one trailing object
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
          kwargs[decode(args + 16 * (npos + nkw + i), false)] = decode(args + 16 * (npos + i), false);
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

/** the operation `op` on the object `h` with the argument slots arg / arg2 */
export function op(op: Op, h: number, arg: number, arg2: number, out: number): number {
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
export function toPy(h: number, depth: number, out: number): number {
  try {
    toStream(h, depth, out);
    return Rc.OK;
  } catch (error) {
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
 * awaited by the suspending import of run_sync: the Python call stack is
 * suspended until the promise `h` settles, its value / error is the result
 */
export async function jspiAwait(h: number, out: number): Promise<number> {
  jspi.suspended = true;
  jspi.depth -= 1;
  try {
    encode(await hGet(h), out, false);
    return Rc.OK;
  } catch (error) {
    return fail(error, out);
  } finally {
    // resumed: back on the promising call stack
    jspi.suspended = false;
    jspi.depth += 1;
    jspi.canSuspend = true;
  }
}

// struct format character -> typed array class
const TYPED_ARRAYS: Record<string, any> = {
  b: Int8Array,
  B: Uint8Array,
  c: Uint8Array,
  "?": Uint8Array,
  h: Int16Array,
  H: Uint16Array,
  i: Int32Array,
  I: Uint32Array,
  l: Int32Array,
  L: Uint32Array,
  q: BigInt64Array,
  Q: BigUint64Array,
  f: Float32Array,
  d: Float64Array,
};

/**
 * a typed array of `nitems` items at `ptr` of the wasm memory (`format`: code
 * of the struct format character): a view of the memory, or a copy
 */
export function typedArray(ptr: number, nitems: number, format: number, view: number, out: number): number {
  try {
    const cls = TYPED_ARRAYS[String.fromCharCode(format)];
    if (cls === undefined) {
      return Rc.ERROR;
    }
    const array = new cls(HEAPU8.buffer, ptr, nitems);
    encode(view !== 0 ? array : array.slice(), out, false);
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
}

/** copy the bytes of a buffer into the wasm memory at `ptr` */
export function bufferCopy(h: number, ptr: number): void {
  HEAPU8.set(bytesOf(hGet(h)), ptr);
}
