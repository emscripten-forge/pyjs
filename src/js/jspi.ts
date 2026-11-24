// JSPI (JavaScript Promise Integration): `pyjs.run_sync(promise)`.
//
// One build for all browsers: JSPI is used when the browser has
// WebAssembly.Suspending / WebAssembly.promising, otherwise pyjs behaves as
// without it (can_run_sync() is False, run_sync raises).
//   - suspend point: the wasm import `pyjs_js_await` (src/js_proxy.cpp),
//     wrapped in WebAssembly.Suspending before instantiation if supported
//   - entry point: the wasm export `pyjs_call_promising` (src/py_entry.cpp),
//     wrapped in WebAssembly.promising (pyproxy.ts)
// Suspending only works with no JS frame between the two, and only one Python
// call stack can be suspended at a time (the C stack stays LIFO).

const wasm: any = typeof WebAssembly !== "undefined" ? WebAssembly : {};

export const jspi = {
  /** the browser has the API */
  supported: typeof wasm.Suspending === "function" && typeof wasm.promising === "function",
  /** switched off at runtime (the tests run one build with and without JSPI) */
  disabled: false,
  /** the innermost JS -> Python entry is a promising one */
  canSuspend: false,
  /** a Python call stack is suspended in run_sync */
  suspended: false,
  /** number of active (not suspended) JS -> wasm entries */
  depth: 0,
};

/** JSPI is used: supported by the browser and not switched off */
export function jspiEnabled(): boolean {
  return jspi.supported && !jspi.disabled;
}

/** run_sync is possible in the Python code running right now */
export function canRunSync(): boolean {
  return jspiEnabled() && jspi.canSuspend && !jspi.suspended;
}
