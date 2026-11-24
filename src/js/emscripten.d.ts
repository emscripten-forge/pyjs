// What the pyjs JavaScript uses from the emscripten runtime it is embedded in
// (the bundle runs in the scope of the generated runtime js).

// views of the wasm memory (replaced when the memory grows: never keep a copy)
declare let HEAPU8: Uint8Array;
declare let HEAP32: Int32Array;
declare let HEAPF64: Float64Array;

// the emscripten Module object
declare const Module: any;

// the exports of the wasm module (after instantiation)
declare const wasmExports: any;

// (pointers are numbers, also on wasm64: emscripten converts for these)
declare function _malloc(size: number): number;
declare function _free(ptr: number): void;

// writes `str` NUL terminated, returns the number of bytes without the NUL
declare function stringToUTF8Array(str: string, heap: Uint8Array, outIdx: number, maxBytesToWrite: number): number;

// what the C side (EM_JS functions) calls, set by index.ts
declare let pj: any;
