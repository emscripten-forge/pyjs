// Entry of the JavaScript side of pyjs.
//
// How this code gets into the runtime: esbuild bundles the files of this
// directory into one script. The build embeds that script into libpyjs.a
// (build_utils/embed_js.cmake), and emscripten pastes it into the runtime js
// it generates when somebody links libpyjs. So this code runs inside the
// runtime script and can use its variables (HEAP32, Module, FS, ...).
//
// The files:
//   codec.ts    values <-> slots in wasm memory (start reading there)
//   deep.ts     whole structures in one go (to_py / to_js)
//   jsops.ts    Python operating on JS objects (Python -> JS)
//   pyproxy.ts  JS operating on Python objects (JS -> Python)
//   jspi.ts     state of run_sync (suspending Python until a promise settles)
//   runtime.ts  Module.startPython, Module.exec, ...
//
// `pj` is the one variable the C++ side knows: each EM_JS function there is a
// one-liner calling a function of this object.
import { initScratch } from "./codec";
import {
  bufferCopy,
  bufferInfo,
  call,
  free,
  getattr,
  getindex,
  jspiAwait,
  name,
  op,
  setattr,
  toJs,
  toPy,
  typedArray,
} from "./jsops";
import { initPyProxy } from "./pyproxy";
import { installModuleApi } from "./runtime";

let initialized = false;

pj = {
  /**
   * Called from C when python is about to start (pyjs_js_prelude). Only now
   * the wasm memory and the wasm exports exist: allocate the scratch region
   * and look up the exported functions.
   */
  init(): void {
    if (!initialized) {
      initScratch();
      initPyProxy();
      initialized = true;
    }
  },
  call,
  getattr,
  getindex,
  setattr,
  name,
  free,
  op,
  typedArray,
  bufferInfo,
  bufferCopy,
  toPy,
  toJs,
  jspiAwait,
};

// runs right away, while the runtime script loads: Module.startPython etc.
installModuleApi();
