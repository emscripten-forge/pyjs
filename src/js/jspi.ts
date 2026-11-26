// JSPI (JavaScript Promise Integration): `pyjs.run_sync(promise)`.
//
// One build for all browsers: JSPI is used when the browser has
// WebAssembly.Suspending / WebAssembly.promising, otherwise pyjs behaves as
// without it (can_run_sync() is False, run_sync raises).
//   - suspend point: the wasm import `pyjs_js_await` (src/js_proxy.cpp),
//     wrapped in WebAssembly.Suspending before instantiation if supported;
//     its JS half is jspiAwait (jsops.ts)
//   - entry point: the wasm export `pyjs_call_promising` (src/py_entry.cpp),
//     wrapped in WebAssembly.promising (callPythonPromising, pyproxy.ts)
// Suspending only works with no JS frame between the two.
//
// Each promising call is a "task". Any number of tasks can be suspended at
// the same time and resume in any order: their C stack data is moved out of
// the way and back by stack_state.ts, their part of CPython's thread state by
// src/stack_switching.c (both derived from pyodide).

const wasm: any = typeof WebAssembly !== "undefined" ? WebAssembly : {};

export const jspi = {
  /** the browser has the API */
  supported: typeof wasm.Suspending === "function" && typeof wasm.promising === "function",
  /** switched off at runtime (the tests run one build with and without JSPI) */
  disabled: false,
  /**
   * The innermost JS -> Python entry that is running is a promising one: the
   * Python code running right now may suspend. False in a synchronous entry
   * (an event handler, a PyProxy method, ...) even if it is nested in a task.
   */
  canSuspend: false,
  /** number of active (not suspended) JS -> wasm entries */
  depth: 0,
};

/**
 * A synchronous entry into Python starts that does not come through a
 * PyProxy (the C callbacks of the main loop / requestAnimationFrame loop,
 * src/module.cpp): counted like the others. Returns what syncLeave needs.
 */
export function syncEnter(): number {
  const couldSuspend = jspi.canSuspend;
  jspi.canSuspend = false;
  jspi.depth += 1;
  return couldSuspend ? 1 : 0;
}

/** the entry of syncEnter ends */
export function syncLeave(couldSuspend: number): void {
  jspi.depth -= 1;
  jspi.canSuspend = couldSuspend !== 0;
}

/** JSPI is used: supported by the browser and not switched off */
export function jspiEnabled(): boolean {
  return jspi.supported && !jspi.disabled;
}

/** run_sync is possible in the Python code running right now */
export function canRunSync(): boolean {
  return jspiEnabled() && jspi.canSuspend;
}
