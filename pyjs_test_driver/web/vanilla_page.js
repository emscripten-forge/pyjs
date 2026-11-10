// page.js of the vanilla page: pyjs from the raw emscripten output
// (pyjs_runtime_browser.js / .wasm) and an empack-packed environment, via the
// classic Module API (bootstrap_from_empack_packed_environment), as used by
// projects consuming pyjs without the npm package (e.g. xeus-python).
const base = new URL("./", import.meta.url).href;

/** the classic (non module) runtime script defines the global createModule */
async function loadClassicRuntime() {
  const source = await (await fetch(`${base}pyjs_runtime_browser.js`)).text();
  (0, eval)(source);  // indirect eval: global scope, works in workers too
  return globalThis.createModule;
}

/** an initialized pyjs (python + the packed test env) */
export async function createPyjs(options) {
  const createModule = await loadClassicRuntime();
  const pyjs = await createModule({ locateFile: (file) => `${base}${file}` });
  await pyjs.bootstrap_from_empack_packed_environment(
    `${base}empack_env_meta.json`,
    base.replace(/\/$/, ""),
    false,
    !(options.preload ?? true)  // skip_loading_shared_libs
  );
  // the bootstrap logs errors instead of throwing them
  if (!pyjs._is_initialized) {
    throw new Error("bootstrap_from_empack_packed_environment failed (see the console)");
  }
  return pyjs;
}
