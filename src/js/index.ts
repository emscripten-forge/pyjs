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
//   stack_state.ts  the C stack data of suspended run_sync calls
//   runtime.ts  Module.startPython, Module.runPython, ...
//
// `pyjsCore` (below) is the JavaScript counterpart of the Python module
// `pyjs_core` (the C++ core): one object holding the JavaScript half of the
// core, i.e. every function the C++ side calls into.
//
// Why one object: the C++ code reaches JavaScript only through EM_JS
// functions (src/js_proxy.cpp, src/module.cpp, src/deep.cpp), and each of
// those is a one-liner like `return pyjsCore.getattr(h, name, out);`. So this
// is the ONLY name of the JavaScript side the C++ side has to know; all other
// code of this directory stays private inside the bundle. The variable itself
// is declared by build_utils/embed_js.cmake (`var pyjsCore;`, at the top
// level of the runtime script, where the EM_JS functions can see it) and
// filled here when the runtime script loads.
//
// (`initScratch`: allocates the "scratch region", a block of wasm memory in
// which JavaScript writes the arguments of its calls into Python; see
// codec.ts.)
import { initScratch } from "./codec";
import {
  bufferCopy,
  bufferInfo,
  call,
  free,
  getattr,
  getindex,
  jspiAwait,
  jspiResume,
  name,
  op,
  setattr,
  toJs,
  toPy,
  typedArray,
} from "./jsops";
import { syncEnter, syncLeave } from "./jspi";
import { initPyProxy, taskDone } from "./pyproxy";
import { bindPython, installModuleApi } from "./runtime";

let initialized = false;

pyjsCore = {
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
  jspiResume,
  taskDone,
  syncEnter,
  syncLeave,
  // pyjs_bind() of the C API (src/py_entry.cpp)
  bind: bindPython,
};

// runs right away, while the runtime script loads: Module.startPython etc.
installModuleApi();
