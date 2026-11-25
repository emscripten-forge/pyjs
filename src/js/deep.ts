// Deep conversion: copying a whole structure (lists in dicts in lists ...)
// between the languages in ONE hop. This is what `to_py()` and `to_js()` use.
//
// THE PROBLEM. The obvious way to copy a JS array into a Python list is to
// ask for every element, one call across the border each. For 100 elements
// that is 100 calls, and for nested data it multiplies.
//
// THE IDEA. Write the whole structure down as a "stream": a run of slots (the
// 16 byte value format of codec.ts) one after the other in wasm memory. The
// other side reads the stream front to back and rebuilds the structure. One
// call, however large the data is.
//
// THE STREAM. Simple values are one slot, as always. A container is a
// "header" slot saying what it is and how many items it has, followed
// directly by its items; an item can again be a container. Example,
//
//     [1, "a", {x: 2}]
//
// becomes these 6 slots:
//
//     LIST 3          a list with 3 items follows
//       INT 1
//       STR "a"
//       DICT 1        a dict with 1 entry follows: key, value
//         STR "x"
//         INT 2
//
// SHARED AND CYCLIC DATA. An object can appear twice in a structure, or even
// contain itself. Writing it out again each time would duplicate it, or never
// end. So containers are numbered in the order their headers are written (0,
// 1, 2, ...), and the second time the same container shows up, only a `REF n`
// slot is written: "the container number n again". The reader numbers the
// containers it creates the same way and puts the same object there.
//
// The two directions:
//   JS -> Python (to_py):  toStream() here writes, src/deep.cpp reads
//   Python -> JS (to_js):  src/deep.cpp writes, fromStream() here reads
//
// This file is, with codec.ts, the only one that reads and writes the fields
// of slots directly (it is the hot loop of the conversion). The layout of a
// slot and the index arithmetic (`i = p / 4`, HEAP32[i + 1], HEAPF64[i / 2 +
// 1]) are explained at the top of codec.ts.
import {
  T,
  PYPROXY,
  decode,
  encode,
  hGet,
  hNew,
  jsFlags,
  pyProxyJsFlags,
  writeAuxAndNum,
  writeJsObject,
} from "./codec";

// ---------------------------------------------------------------------------
// JS -> Python: writing a stream
//
// Two blocks of wasm memory are used, both kept and reused for the next
// conversion (so a conversion normally allocates nothing):
//
//   the slot block     the stream itself
//   the text block     the utf8 bytes of all strings of the stream
//
// A string slot cannot hold the ADDRESS of its text as usual, because the
// text block may have to grow while the stream is written, which moves it.
// It holds the OFFSET of the text inside the text block; the reader adds the
// address of the block.
//
// The blocks are only valid until the next conversion. That is fine because
// the C side reads the stream completely before anything else can run.
// ---------------------------------------------------------------------------
let slots = 0; // address of the slot block
let slotCapacity = 0; // how many slots fit
let slotCount = 0; // how many are written
let text = 0; // address of the text block
let textCapacity = 0; // its size in bytes
let textLength = 0; // how many bytes are written

// the containers written so far -> their number (for REF)
let seen: Map<object, number> | null = null;

// struct format character (see formatOf) -> the typed array class with items
// of that type
const ARRAY_CLASSES: Record<string, any> = {
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

// the reverse: typed array class -> its struct format character
const FORMATS = new Map<any, string>([
  [Int8Array, "b"],
  [Uint8Array, "B"],
  [Uint8ClampedArray, "B"],
  [Int16Array, "h"],
  [Uint16Array, "H"],
  [Int32Array, "i"],
  [Uint32Array, "I"],
  [BigInt64Array, "q"],
  [BigUint64Array, "Q"],
  [Float32Array, "f"],
  [Float64Array, "d"],
]);

/** move a block to a bigger one, keeping its `used` bytes; returns the new address */
function grow(old: number, used: number, size: number): number {
  const block = _malloc(size);
  if (old !== 0) {
    HEAPU8.copyWithin(block, old, old + used);
    _free(old);
  }
  return block;
}

/** make sure one more slot fits; returns the address to write it to */
function nextSlot(): number {
  if (slotCount === slotCapacity) {
    slotCapacity = Math.max(1024, 2 * slotCapacity);
    slots = grow(slots, 16 * slotCount, 16 * slotCapacity);
  }
  return slots + 16 * slotCount++;
}

/** write a slot with a tag and the integer field `aux` (e.g. a container header) */
function writeHeader(tag: number, aux: number): void {
  const i = nextSlot() / 4;
  HEAP32[i] = tag;
  HEAP32[i + 1] = aux;
}

/** write a string slot (tag STR or BIGINT): the text goes into the text block */
function writeText(tag: number, str: string): void {
  // room for the worst case: 3 bytes per unit of the JS string, + the closing 0
  const needed = textLength + 3 * str.length + 1;
  if (needed > textCapacity) {
    textCapacity = Math.max(1 << 16, 2 * needed);
    text = grow(text, textLength, textCapacity);
  }
  const start = text + textLength;
  // plain ASCII (the common case) is copied directly ...
  const n = str.length;
  let length = 0;
  for (; length < n; length++) {
    const c = str.charCodeAt(length);
    if (c > 127) {
      break;
    }
    HEAPU8[start + length] = c;
  }
  if (length < n) {
    // ... anything else is converted by emscripten
    length = stringToUTF8Array(str, HEAPU8, start, textCapacity - textLength);
  } else {
    HEAPU8[start + length] = 0;
  }
  const i = nextSlot() / 4;
  HEAP32[i] = tag;
  HEAP32[i + 1] = length;
  HEAPF64[i / 2 + 1] = textLength; // the OFFSET in the text block, see above
  textLength += length + 1;
}

/**
 * The item type of a typed array as "struct format character", the
 * one-letter codes Python uses for the same thing (memoryview.format, the
 * `struct` and `array` modules): "d" is a 64 bit float, "B" an unsigned
 * byte, ... An ArrayBuffer or DataView has no item type: plain bytes, "B".
 */
function formatOf(value: any): string {
  // (looked up by the class of the object: one step, no chain of instanceof)
  return FORMATS.get(value.constructor) ?? "B";
}

/**
 * If `value` was written before: write a REF to it and return true.
 * Otherwise give it the next container number and return false.
 */
function writtenBefore(value: object): boolean {
  // (the map is only created when the first container shows up: converting a
  // single typed array or a simple value needs none)
  seen ??= new Map();
  const number = seen.get(value);
  if (number !== undefined) {
    writeHeader(T.REF, number);
    return true;
  }
  seen.set(value, seen.size);
  return false;
}

/**
 * Write `value` to the stream, containers `depth` levels deep (-1: all the
 * way down). What is not converted is written as an ordinary slot: Python
 * gets a proxy for it.
 */
/** a list of the DOM (NodeList, HTMLCollection): converted like an Array */
function isDomList(value: any): boolean {
  const tag = Object.prototype.toString.call(value);
  return tag === "[object NodeList]" || tag === "[object HTMLCollection]";
}

/**
 * The keys of a Map / the items of a Set that becomes a Python dict / set.
 * Throws (python gets a JSException) when that cannot work:
 *   - a key that is copied into a Python container (an Array becomes a
 *     list): lists, dicts and sets cannot be keys in python
 *   - 0 and false (or 1 and true) both as keys: different keys in
 *     JavaScript, the same key in python (False == 0), one would be lost
 */
function checkKeys(container: Map<any, any> | Set<any>, target: string): void {
  for (const key of container.keys()) {
    if (Array.isArray(key) || key instanceof Map || key instanceof Set) {
      throw new TypeError(`Cannot use key of type ${key.constructor.name} as a key to a Python ${target}`);
    }
  }
  for (const [number, bool] of [
    [0, false],
    [1, true],
  ]) {
    if (container.has(number) && container.has(bool)) {
      throw new TypeError(
        `Cannot convert to a Python ${target}: it contains both ${number} and ${bool}, which are the same key in python`
      );
    }
  }
}

function write(value: any, depth: number): void {
  switch (typeof value) {
    case "number": {
      const i = nextSlot() / 4;
      HEAP32[i] = Number.isSafeInteger(value) ? T.INT : T.FLOAT;
      HEAPF64[i / 2 + 1] = value;
      return;
    }
    case "string":
      writeText(T.STR, value);
      return;
    case "boolean":
      writeHeader(value ? T.TRUE : T.FALSE, 0);
      return;
    case "undefined":
      writeHeader(T.UNDEF, 0);
      return;
    case "bigint":
      writeText(T.BIGINT, value.toString());
      return;
    case "object":
      if (value === null) {
        writeHeader(T.NULL, 0);
        return;
      }
      if (depth !== 0) {
        // the containers that are copied (the same choice as PEP 818)
        // (the lists of the DOM, e.g. document.querySelectorAll(...), are
        // copied like Arrays)
        if (Array.isArray(value) || isDomList(value)) {
          if (!writtenBefore(value)) {
            const n = value.length;
            writeHeader(T.LIST, n);
            for (let k = 0; k < n; k++) {
              write(value[k], depth - 1);
            }
          }
          return;
        }
        if (value instanceof Map) {
          if (!writtenBefore(value)) {
            checkKeys(value, "dict");
            writeHeader(T.DICT, value.size);
            for (const [key, item] of value) {
              write(key, depth - 1);
              write(item, depth - 1);
            }
          }
          return;
        }
        if (value instanceof Set) {
          if (!writtenBefore(value)) {
            checkKeys(value, "set");
            writeHeader(T.SET, value.size);
            for (const item of value) {
              write(item, depth - 1);
            }
          }
          return;
        }
        if (ArrayBuffer.isView(value) || value instanceof ArrayBuffer) {
          // The bytes are not put into the stream (that would copy them
          // twice). Python gets a handle, the size and the item type, and
          // fetches the bytes straight into the Python object it creates
          // (bufferCopy in jsops.ts).
          const i = nextSlot() / 4;
          // the item type travels in the upper half of the tag
          HEAP32[i] = T.BUFFER | (formatOf(value).charCodeAt(0) << 16);
          HEAP32[i + 1] = hNew(value);
          HEAPF64[i / 2 + 1] = value.byteLength;
          return;
        }
        // A "plain" object, as written with {...}: its constructor is Object
        // (or it has none). Instances of classes are NOT copied: they are
        // objects with behaviour, not data, and stay proxies.
        const constructor = value.constructor;
        if ((constructor === Object || constructor === undefined) && value[PYPROXY] === undefined) {
          if (!writtenBefore(value)) {
            const keys = Object.keys(value);
            writeHeader(T.DICT, keys.length);
            for (let k = 0; k < keys.length; k++) {
              writeText(T.STR, keys[k]);
              write(value[keys[k]], depth - 1);
            }
          }
          return;
        }
      }
      break;
  }
  // everything else (functions, class instances, PyProxies, containers below
  // the depth limit): the normal implicit conversion, i.e. a proxy
  encode(value, nextSlot(), false);
}

/**
 * to_py: write the JS object with handle `h` as stream (see the top of this
 * file). The result, in the two slots at `out`:
 *   out          aux: the number of slots, num: the address of the slot block
 *   out + 16     num: the address of the text block
 */
export function toStream(h: number, depth: number, out: number): void {
  slotCount = 0;
  textLength = 0;
  seen = null;
  try {
    write(hGet(h), depth);
  } finally {
    seen = null; // (do not keep the objects alive)
  }
  writeAuxAndNum(out, slotCount, slots);
  writeAuxAndNum(out + 16, 0, text);
}

// ---------------------------------------------------------------------------
// Python -> JS: reading a stream
// ---------------------------------------------------------------------------
let cursor = 0; // address of the next slot to read
let created: any[] = []; // the containers created so far, by number (for REF)

/** read the next value of the stream (a container: with all its items) */
function read(): any {
  const p = cursor;
  cursor += 16;
  const i = p / 4;
  const tag = HEAP32[i];
  switch (tag & 0xff) {
    case T.LIST: {
      const n = HEAP32[i + 1];
      const array = new Array(n);
      // (registered before its items are read: an item may be a REF to it)
      created.push(array);
      for (let k = 0; k < n; k++) {
        array[k] = read();
      }
      return array;
    }
    case T.DICT: {
      const n = HEAP32[i + 1];
      const object: Record<any, any> = {};
      created.push(object);
      for (let k = 0; k < n; k++) {
        const key = read();
        object[key] = read();
      }
      return object;
    }
    case T.SET: {
      const n = HEAP32[i + 1];
      const set = new Set();
      created.push(set);
      for (let k = 0; k < n; k++) {
        set.add(read());
      }
      return set;
    }
    case T.REF:
      return created[HEAP32[i + 1]];
    case T.BUFFER: {
      // A Python buffer (bytes, a numpy array, ...): `num` is the address of
      // its memory, `aux` the number of items, and the item type (a struct
      // format character) sits in the upper half of the tag. `slice()`
      // makes the copy; without it the array would be a window into Python's
      // memory, which can move or be freed.
      const cls = ARRAY_CLASSES[String.fromCharCode(tag >> 16)];
      return new cls(HEAPU8.buffer, HEAPF64[i / 2 + 1], HEAP32[i + 1]).slice();
    }
    default:
      // A simple value, or a Python object that is not converted: that one
      // becomes a PyProxy which lives on inside the converted structure
      // ("owned"), not one that dies when a call returns.
      return decode(p, true);
  }
}

/**
 * to_js: build the JS value of the stream of slots at `stream` (written by
 * src/deep.cpp) and write it, as ordinary slot, to `out`.
 */
export function fromStream(stream: number, out: number): void {
  cursor = stream;
  created = [];
  try {
    const value = read();
    // (not encode(): a top level PyProxy must reach Python as proxy, like
    // every other JS object here, not be unwrapped into its Python object.
    // Its flags come from the Python object: a JSDoubleProxy, with unwrap())
    // (a PyProxy of a callable is a function)
    const state =
      value !== null && (typeof value === "object" || typeof value === "function") ? value[PYPROXY] : undefined;
    writeJsObject(out, value, state !== undefined ? pyProxyJsFlags(state) : jsFlags(value));
  } finally {
    created = []; // (do not keep the objects alive)
  }
}
