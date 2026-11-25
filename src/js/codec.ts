// The wire format between Python (wasm) and JavaScript.
//
// THE PROBLEM. Python runs inside WebAssembly. Wasm and JavaScript can only
// pass plain numbers to each other, and every call across that border costs
// time. A naive bridge makes several such calls per value ("is it a string?",
// "how long?", "give me the bytes", ...).
//
// THE IDEA. Both sides can read and write the same block of memory (the wasm
// memory, visible in JS as the arrays HEAPU8 / HEAP32 / HEAPF64). So instead
// of calling back and forth, a value is written into that memory in a fixed
// 16 byte layout, a "slot", and only its address is passed. One call is then
// enough for a whole operation: the caller writes the argument slots, makes
// the call, and reads the result slot afterwards.
//
// A SLOT (16 bytes at address p):
//
//     byte   0 ..  3    tag   (int32)   what kind of value this is, see T
//     byte   4 ..  7    aux   (int32)   meaning depends on the tag
//     byte   8 .. 15    num   (float64) meaning depends on the tag
//            or two int32:  a (bytes 8 .. 11) and b (bytes 12 .. 15)
//
//   examples:
//     the number 1.5      tag = FLOAT, num = 1.5
//     the string "hi"     tag = STR,   aux = 2 (bytes), num = address of the
//                                      utf8 bytes 'h' 'i'
//     a JS object         tag = JS,    aux = its handle (see "handles" below)
//     a Python object     tag = PY,    num = its address (a PyObject*)
//
// HOW JS READS A SLOT. HEAP32 is the memory seen as 32 bit integers, so the
// integer at address p is HEAP32[p / 4]. HEAPF64 is the memory seen as 64 bit
// floats, so the float at address p + 8 is HEAPF64[(p + 8) / 8]. The code
// computes `i = p / 4` once and then uses
//
//     HEAP32[i]          tag
//     HEAP32[i + 1]      aux
//     HEAPF64[i / 2 + 1] num      ((p + 8) / 8  =  p / 8 + 1  =  i / 2 + 1)
//     HEAP32[i + 2]      a
//     HEAP32[i + 3]      b
//
// Slots always start at a multiple of 16, so these divisions are exact.
//
// ADDRESSES ARE PLAIN NUMBERS. A JS number holds integers exactly up to 2^53,
// far more than any address, on wasm32 and on wasm64. The C side passes
// addresses as `double` for that reason: the same code works for both and no
// BigInt is involved.
//
// The C++ side of all this is src/slot.hpp. The tag / flag numbers below must
// be identical there.

/** slot tags */
export const enum T {
  UNDEF = 0,
  NULL = 1,
  FALSE = 2,
  TRUE = 3,
  INT = 4,
  FLOAT = 5,
  STR = 6, // double: pointer to utf8, aux: length in bytes
  BIGINT = 7, // like STR: the decimal digits
  JS = 8, // aux: handle, int a: flags, int b: handle of `this`
  PY = 9, // double: PyObject*, aux: flags
  ERROR = 10, // aux: handle of the thrown value, or (aux 0) double: the Python exception
  // only inside the slot streams of a deep conversion (deep.ts explains them)
  LIST = 11, // aux: number of items, which follow
  DICT = 12, // aux: number of entries; key, value, key, value ... follow
  SET = 13, // aux: number of items, which follow
  REF = 14, // aux: index of a container that came earlier in the stream
  BUFFER = 15, // a typed array, see deep.ts
  OWNED = 0x100, // or-ed to STR / BIGINT: the receiver frees the buffer
}

/** what a JS object can do: selects the Python type of its JSProxy */
export const enum JsFlag {
  CALLABLE = 1,
  LENGTH = 2,
  CONTAINS = 4,
  ITERABLE = 8,
  ITERATOR = 16,
  AWAITABLE = 32,
  GETITEM = 64, // obj[key] in python: a sequence, or it has get()
  SETITEM = 128, // obj[key] = value in python: a sequence, or it has set()
  // The following select Python classes with extra methods that the proxy
  // type derives from (pyjs/_proxy_types.py), e.g. append() for an Array.
  ARRAY = 256, // an Array
  BUFFER = 512, // a typed array, DataView or ArrayBuffer
  MAP = 1024, // like a Map: get(), has(), size, iterable
  GENERATOR = 2048, // an iterator with return() and throw()
  ASYNC_ITERABLE = 4096, // has [Symbol.asyncIterator]
  ASYNC_ITERATOR = 8192, // next() returns promises
  ERROR = 16384, // an Error: python gets a JSException for it
  DOUBLE_PROXY = 32768, // a PyProxy made by create_proxy (python: JSDoubleProxy)
}

/**
 * The JsFlags of a PyProxy (a JS object standing for a Python object), from
 * what the Python object can do: the C side determined that already, so the
 * proxy need not be probed (every probe would be a call into Python).
 */
export function pyProxyJsFlags(state: { flags: number }): number {
  const pyFlags = state.flags;
  return (
    (pyFlags & PyFlag.CALLABLE ? JsFlag.CALLABLE : 0) |
    (pyFlags & PyFlag.AWAITABLE ? JsFlag.AWAITABLE : 0) |
    (pyFlags & PyFlag.ITERABLE ? JsFlag.ITERABLE : 0) |
    (pyFlags & PyFlag.ITERATOR ? JsFlag.ITERATOR : 0) |
    (pyFlags & PyFlag.SIZED ? JsFlag.LENGTH : 0) |
    // (a JSProxy of a PyProxy is always a JSDoubleProxy in python)
    JsFlag.DOUBLE_PROXY
  );
}

/** what a Python object can do (computed by the C side) */
export const enum PyFlag {
  CALLABLE = 1,
  AWAITABLE = 2,
  ITERABLE = 4,
  ITERATOR = 8,
  SIZED = 16, // has len()
  GENERATOR = 32, // a generator: send / throw / close
}

// ---------------------------------------------------------------------------
// handles: how Python refers to a JS object
//
// Python cannot hold a JS object, only a number. So every JS object Python
// knows about is stored in the array `objects`, and Python keeps its index:
// the "handle". Handle 5 simply means objects[5].
//
// Who cleans up: the Python object holding a handle (a JSProxy) owns it. When
// that Python object dies, the C side calls hFree, the entry is emptied (so
// the JS garbage collector can reclaim the JS object) and the index is put
// into `freeHandles` to be reused by the next hNew.
//
// The same JS object can have several handles at once; that is fine, each
// JSProxy frees its own.
// ---------------------------------------------------------------------------
const objects: any[] = [undefined]; // index 0 is never used: 0 means "no handle"
const freeHandles: number[] = []; // indices of `objects` that are free again

/** a handle for `value` (owned by the caller: hFree) */
export function hNew(value: any): number {
  const h = freeHandles.length > 0 ? freeHandles.pop()! : objects.length;
  objects[h] = value;
  return h;
}

export function hGet(h: number): any {
  return objects[h];
}

export function hFree(h: number): void {
  if (h !== 0) {
    objects[h] = undefined;
    freeHandles.push(h);
  }
}

// ---------------------------------------------------------------------------
// scratch memory: where JS writes what it sends to Python
//
// When JS calls Python it needs wasm memory for the argument slots and for
// the bytes of string arguments. Asking the allocator (malloc / free) for
// every call would cost two extra calls into wasm each time. Instead one
// region of 64 KiB is allocated once and used like a stack:
//
//     scratchTop ->  first free byte; everything below is in use
//
//   - a call notes the current top (scratchMark)
//   - writes its slots and strings, moving the top up
//   - calls Python
//   - puts the top back (scratchRelease): its data is no longer needed,
//     Python has turned the arguments into Python objects by then
//
// Calls can nest (JS calls Python, which calls JS, which calls Python ...):
// the inner call starts above the data of the outer one and gives its part
// back before the outer one continues, so nothing is overwritten.
//
// What does not fit into the region (a huge string, hundreds of arguments) is
// allocated with malloc instead; see the OWNED flag and the callers of
// scratchSlots.
// ---------------------------------------------------------------------------
const SCRATCH_SIZE = 1 << 16; // 64 KiB
let scratchTop = 0; // address of the first free byte of the region
let scratchEnd = 0; // address just behind the region

/** allocate the scratch region (once the wasm memory exists) */
export function initScratch(): void {
  scratchTop = _malloc(SCRATCH_SIZE);
  scratchEnd = scratchTop + SCRATCH_SIZE;
}

/** the current top, to be given back to scratchRelease */
export function scratchMark(): number {
  return scratchTop;
}

export function scratchRelease(mark: number): void {
  scratchTop = mark;
}

/**
 * reserve `n` slots in the scratch region and return their address;
 * 0 if they do not fit (the caller then uses malloc)
 */
export function scratchSlots(n: number): number {
  // Strings written before may have left the top at an odd address. A slot
  // contains a float64, which must start at a multiple of 8: round up.
  // ((x + 7) & ~7 is "the next multiple of 8 at or above x")
  const ptr = (scratchTop + 7) & ~7;
  if (ptr + 16 * n > scratchEnd) {
    return 0;
  }
  scratchTop = ptr + 16 * n;
  return ptr;
}

// ---------------------------------------------------------------------------
// strings
// ---------------------------------------------------------------------------
// (ignoreBOM: a TextDecoder normally swallows a "byte order mark", the
// character U+FEFF, at the start of the text. A python string that starts
// with that character must arrive unchanged.)
const utf8Decoder = new TextDecoder("utf-8", { ignoreBOM: true });

/** the string of `len` utf8 bytes at `ptr` */
export function utf8(ptr: number, len: number): string {
  if (len < 24) {
    // short and ascii (attribute names, ...): cheaper than the TextDecoder
    let str = "";
    let i = 0;
    for (; i < len; i++) {
      const c = HEAPU8[ptr + i];
      if (c > 127) {
        break;
      }
      str += String.fromCharCode(c);
    }
    if (i === len) {
      return str;
    }
  }
  return utf8Decoder.decode(HEAPU8.subarray(ptr, ptr + len));
}

/**
 * Send a JS string to Python: write its bytes (utf8) into wasm memory and
 * fill the slot `i` (index into HEAP32) with their address and length.
 *
 * Where the bytes go: into the scratch region if they fit. If not, into
 * memory from malloc; the slot is then marked OWNED, which tells the C side
 * "free this buffer when you have read it".
 *
 * `advance` says whether the bytes must stay untouched for a while:
 *   - true for arguments of a call: several arguments are written one after
 *     the other and all must survive until Python has read them, so the top
 *     of the scratch region moves up behind the string.
 *   - false for a result: the C side reads it immediately after we return,
 *     nothing else is written in between, so the top stays where it is and
 *     the next write simply reuses the bytes.
 */
function encodeString(str: string, i: number, tag: number, advance: boolean): void {
  const n = str.length;
  // How much room is needed is only known after converting. The worst case
  // is 3 bytes for each of the `n` units of the JS string, plus one byte for
  // the closing 0.
  const capacity = 3 * n + 1;
  let ptr = scratchTop;
  if (ptr + capacity > scratchEnd) {
    // does not fit into the scratch region
    ptr = _malloc(capacity);
    tag |= T.OWNED;
    advance = false; // (the scratch region was not used)
  }
  // Fast path: most strings are plain ASCII, where one character is one
  // byte. Copy bytes until the first character that is not ASCII ...
  let len = 0;
  for (; len < n; len++) {
    const c = str.charCodeAt(len);
    if (c > 127) {
      break;
    }
    HEAPU8[ptr + len] = c;
  }
  if (len < n) {
    // ... there was one: let emscripten convert the whole string properly
    // (it writes the closing 0 and returns the number of bytes before it)
    len = stringToUTF8Array(str, HEAPU8, ptr, capacity);
  } else {
    HEAPU8[ptr + len] = 0; // the closing 0 (the C side wants it for BIGINT)
  }
  if (advance) {
    scratchTop = ptr + len + 1;
  }
  HEAP32[i] = tag;
  HEAP32[i + 1] = len;
  HEAPF64[i / 2 + 1] = ptr;
}

// ---------------------------------------------------------------------------
// Reading and writing the fields of a slot.
//
// These few functions are the ONLY place (besides encode / decode below) that
// knows where a field sits inside a slot. Everything else calls them by name,
// so that nobody has to decode something like `HEAP32[p / 4 + 3]` in their
// head. For the layout and the index arithmetic see the top of this file.
// ---------------------------------------------------------------------------
/** the tag of the slot at `p`: what kind of value it holds (see T) */
export function slotTag(p: number): number {
  return HEAP32[p / 4];
}

/** the float64 field `num` of the slot at `p` (a number, or an address) */
export function slotNum(p: number): number {
  return HEAPF64[p / 8 + 1];
}

/** the string of a STR slot at `p`: `num` is the address, `aux` the length */
export function slotString(p: number): string {
  return utf8(HEAPF64[p / 8 + 1], HEAP32[p / 4 + 1]);
}

/**
 * Fill the slot at `p` with a JS object: Python will get a JSProxy for it.
 * `flags` say what the object can do (JsFlag), which decides the Python type
 * of the proxy. A new handle is created; the JSProxy owns and later frees it.
 */
export function writeJsObject(p: number, value: any, flags: number): void {
  const i = p / 4;
  HEAP32[i] = T.JS;
  HEAP32[i + 1] = hNew(value); // field aux: the handle
  HEAP32[i + 2] = flags; // field a
  HEAP32[i + 3] = 0; // field b: no `this`, see bindThis
}

/**
 * Make the function in the slot at `p` a method of `obj`.
 *
 * In JavaScript `obj.method(1)` runs `method` with `this` set to `obj`. But
 * Python splits that expression in two steps: first `f = obj.method`, then
 * `f(1)`. Called on its own, the function would have lost its object (`this`
 * would be undefined) and most methods would fail.
 *
 * So when Python fetches a function from an object, the slot also carries a
 * handle of that object (slot field `b`). The JSProxy of the function keeps
 * it and passes it back on every call (parameter `self` of `call` in
 * jsops.ts), where it becomes `this` again.
 *
 * Does nothing if the slot does not hold a JS object (e.g. the function is a
 * Python callable stored in a JS object: that needs no `this`).
 */
export function bindThis(p: number, obj: any): void {
  const i = p / 4;
  if (HEAP32[i] === T.JS) {
    HEAP32[i + 3] = hNew(obj); // freed by the JSProxy together with its own handle
  }
}

/**
 * Fill the slot at `p` with "JavaScript threw `error`". Python gets a JSProxy
 * of the thrown value (with `flags`) and raises an exception for it.
 */
export function writeJsError(p: number, error: any, flags: number): void {
  const i = p / 4;
  HEAP32[i] = T.ERROR;
  HEAP32[i + 1] = hNew(error); // field aux: the handle (never 0)
  HEAP32[i + 2] = flags; // field a
}

/**
 * Fill the slot at `p` with "this Python exception passed through JavaScript"
 * (`exception`: its address). Python raises that very exception again. The
 * handle field is 0, which is how the C side tells the two kinds of error
 * slot apart.
 */
export function writePythonError(p: number, exception: number): void {
  const i = p / 4;
  HEAP32[i] = T.ERROR;
  HEAP32[i + 1] = 0; // field aux: no handle
  HEAPF64[i / 2 + 1] = exception; // field num: the address
}

/** fill the fields `aux` and `num` of the slot at `p` (the tag is not set) */
export function writeAuxAndNum(p: number, aux: number, num: number): void {
  HEAP32[p / 4 + 1] = aux;
  HEAPF64[p / 8 + 1] = num;
}

// ---------------------------------------------------------------------------
// PyProxy hooks (pyproxy.ts registers them: codec.ts does not import it)
// ---------------------------------------------------------------------------
/** key of the state of a PyProxy: `value[PYPROXY]` is undefined for other values */
export const PYPROXY = Symbol("pyjs.pyproxy");

let newPyProxy: (ptr: number, flags: number, owned: boolean) => any;

export function setPyProxyFactory(factory: (ptr: number, flags: number, owned: boolean) => any): void {
  newPyProxy = factory;
}

// ---------------------------------------------------------------------------
// JS object features
// ---------------------------------------------------------------------------
/**
 * Is `value` indexed by position, like a list: an Array or a typed array
 * (Uint8Array, Float64Array, ...)? Those are what `obj[3]` and `obj[-1]` in
 * python address by index.
 * (ArrayBuffer.isView is also true for a DataView, which has no indices.)
 */
export function isSequence(value: any): boolean {
  return Array.isArray(value) || (ArrayBuffer.isView(value) && !(value instanceof DataView));
}

/**
 * What a JS object / function can do, as JsFlag bits. Python decides from
 * these which operations the proxy of the object supports: e.g. `len(proxy)`
 * only works with LENGTH, `proxy[key]` only with GETITEM. So an object is
 * probed once, when its proxy is created, instead of on every operation.
 */
export function jsFlags(value: any): number {
  let flags = typeof value === "function" ? JsFlag.CALLABLE : 0;
  try {
    if (Array.isArray(value)) {
      // the common case, without probing: everything a list can do
      return (
        JsFlag.LENGTH | JsFlag.CONTAINS | JsFlag.ITERABLE | JsFlag.GETITEM | JsFlag.SETITEM | JsFlag.ARRAY
      );
    }
    if (typeof value.then === "function") {
      flags |= JsFlag.AWAITABLE;
    }
    const iterable = typeof value[Symbol.iterator] === "function";
    const asyncIterable = typeof value[Symbol.asyncIterator] === "function";
    if (iterable) {
      flags |= JsFlag.ITERABLE;
    }
    if (asyncIterable) {
      flags |= JsFlag.ASYNC_ITERABLE;
    }
    if (typeof value.next === "function") {
      // An iterator. Whether its next() returns values or promises of values
      // (an async iterator) cannot be seen without calling it. The hint
      // (the same rule as pyodide): iterators say what they are by also
      // being iterable ([Symbol.iterator]) or async iterable. One that says
      // neither is offered to python as both.
      if (iterable || !asyncIterable) {
        flags |= JsFlag.ITERATOR;
      }
      if (asyncIterable || !iterable) {
        flags |= JsFlag.ASYNC_ITERATOR;
      }
      if (typeof value.return === "function" && typeof value.throw === "function") {
        flags |= JsFlag.GENERATOR;
      }
    }
    if (flags & JsFlag.CALLABLE) {
      // (the length of a function is its number of parameters)
      return flags;
    }
    const sized = typeof value.length === "number" || typeof value.size === "number";
    if (sized) {
      flags |= JsFlag.LENGTH;
    }
    const hasHas = typeof value.has === "function";
    if (hasHas || typeof value.includes === "function") {
      flags |= JsFlag.CONTAINS;
    }
    // obj[key]: by position for typed arrays, otherwise through the get() /
    // set() methods containers like Map have. A plain object has neither:
    // its properties are attributes in python (obj.name), not items.
    const sequence = isSequence(value);
    const hasGet = typeof value.get === "function";
    // "Array-likes": objects of the browser that are no Arrays but are used
    // like one, e.g. a NodeList (document.querySelectorAll) or an
    // HTMLCollection (element.children). They have a length and can be
    // iterated; python may read their items by index.
    const arrayLike = typeof value.length === "number" && iterable && !(flags & JsFlag.ITERATOR);
    if (sequence || hasGet || arrayLike) {
      flags |= JsFlag.GETITEM;
    }
    if (sequence || typeof value.set === "function") {
      flags |= JsFlag.SETITEM;
    }
    // everything python needs to treat it like a dict (keys(), items(), ...)
    if (hasGet && hasHas && sized && iterable) {
      flags |= JsFlag.MAP;
    }
    if (ArrayBuffer.isView(value) || value instanceof ArrayBuffer) {
      flags |= JsFlag.BUFFER;
    }
    // (DOMException is an Error too, in every current browser)
    if (value instanceof Error) {
      flags |= JsFlag.ERROR;
    }
  } catch {
    // exotic objects (throwing getters): what was found so far
  }
  return flags;
}

// ---------------------------------------------------------------------------
// the conversion
// ---------------------------------------------------------------------------
/**
 * JS value -> slot. Writes `value` into the slot at address `p`, so that the
 * C side can turn it into a Python object. This is the "implicit conversion":
 *
 *     undefined          -> None
 *     null               -> jsnull
 *     true / false       -> True / False
 *     a number           -> int if it is a whole number, else float
 *     a string           -> str
 *     a BigInt           -> int (its digits are sent as text)
 *     a PyProxy          -> the Python object it stands for (unwrapped)
 *     any other object   -> a JSProxy: the object stays in JS, Python gets a
 *                           handle to it
 *
 * `advance`: only matters for strings, see encodeString.
 *
 * Ownership: for "any other object" a NEW handle is created here. The C side
 * must put it into a JSProxy (which frees it later), otherwise it leaks.
 */
export function encode(value: any, p: number, advance: boolean): void {
  const i = p / 4; // index of the slot in HEAP32, see the top of the file
  switch (typeof value) {
    case "undefined":
      HEAP32[i] = T.UNDEF;
      return;
    case "boolean":
      HEAP32[i] = value ? T.TRUE : T.FALSE;
      return;
    case "number":
      HEAP32[i] = Number.isSafeInteger(value) ? T.INT : T.FLOAT;
      HEAPF64[i / 2 + 1] = value;
      return;
    case "string":
      encodeString(value, i, T.STR, advance);
      return;
    case "bigint":
      encodeString(value.toString(), i, T.BIGINT, advance);
      return;
    default: {
      if (value === null) {
        HEAP32[i] = T.NULL;
        return;
      }
      // Is it a PyProxy, i.e. a JS stand-in for a Python object? Only those
      // answer this property (everything else gives undefined). Then Python
      // must get its own object back, not a proxy of a proxy.
      let state;
      try {
        state = value[PYPROXY];
      } catch {
        // Exotic objects throw on any property access (a revoked Proxy).
        // They are no PyProxy; python gets an ordinary JSProxy of them.
      }
      if (state !== undefined) {
        if (state.ptr === 0) {
          // destroy() was called on it: the Python object is gone
          throw new Error(state.destroyed);
        }
        if (state.roundtrip) {
          // made by create_proxy(obj): python gets the proxy back (a
          // JSDoubleProxy, with destroy() / unwrap()), not `obj` itself
          writeJsObject(p, value, pyProxyJsFlags(state));
          return;
        }
        HEAP32[i] = T.PY;
        HEAPF64[i / 2 + 1] = state.ptr; // the address of the Python object
        return;
      }
      // an ordinary JS object or function: Python gets a handle
      writeJsObject(p, value, jsFlags(value));
    }
  }
}

// "Borrowed" proxies.
//
// When Python calls a JS function and passes a Python object (say a list),
// JS receives a PyProxy for it. Somebody has to release that proxy again, or
// the list would stay alive forever. The rule (the same as in pyodide): such
// a proxy only lives for the duration of the call and is destroyed
// automatically afterwards. It is "borrowed". JS code that wants to keep the
// object must be given one made with create_proxy on the Python side.
//
// decode() collects the borrowed proxies it creates in this list; the code
// running the call picks them up with takeBorrowed() and destroys them when
// the call is over (jsops.ts).
let borrowed: any[] | null = null;

/** the proxies created by decode(p, false) since the last call (or null) */
export function takeBorrowed(): any[] | null {
  const proxies = borrowed;
  borrowed = null;
  return proxies;
}

/**
 * slot -> JS value. Reads the slot at address `p`, which the C side filled
 * from a Python object. The implicit conversion in the other direction:
 *
 *     None               -> undefined
 *     jsnull             -> null
 *     True / False       -> true / false
 *     int, float         -> number (a huge int: BigInt)
 *     str                -> string
 *     a JSProxy          -> the JS object it stands for (unwrapped)
 *     any other object   -> a PyProxy: the object stays in Python
 *
 * `owned` decides who releases such a PyProxy:
 *   - true:  whoever receives it (e.g. the result of calling a Python
 *            function from JS). They should call destroy(); if they forget,
 *            the garbage collector does it eventually.
 *   - false: borrowed, see above: it is destroyed when the current call from
 *            Python ends.
 */
export function decode(p: number, owned: boolean): any {
  const i = p / 4; // index of the slot in HEAP32, see the top of the file
  switch (HEAP32[i]) {
    case T.UNDEF:
      return undefined;
    case T.NULL:
      return null;
    case T.FALSE:
      return false;
    case T.TRUE:
      return true;
    case T.INT:
    case T.FLOAT:
      return HEAPF64[i / 2 + 1];
    case T.STR:
      return utf8(HEAPF64[i / 2 + 1], HEAP32[i + 1]);
    case T.JS:
      return objects[HEAP32[i + 1]];
    case T.PY: {
      const proxy = newPyProxy(HEAPF64[i / 2 + 1], HEAP32[i + 1], owned);
      if (!owned) {
        (borrowed ??= []).push(proxy);
      }
      return proxy;
    }
    case T.BIGINT:
      return BigInt(utf8(HEAPF64[i / 2 + 1], HEAP32[i + 1]));
    case T.BIGINT | T.OWNED: {
      const ptr = HEAPF64[i / 2 + 1];
      const value = BigInt(utf8(ptr, HEAP32[i + 1]));
      _free(ptr);
      return value;
    }
    default:
      throw new Error(`pyjs: unknown slot tag ${HEAP32[i]}`);
  }
}
