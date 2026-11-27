/** pyjs runtime for wasm32 (the default entry of the package). */
import { compileRuntime as compile, initialize } from "./runtime";
import type { IAssetsOptions, IInitializeOptions, PyjsModule } from "./types";

export * from "./types";
export { DEFAULT_CHANNELS, DEFAULT_CDN_URL, PACKAGE_NAME, PACKAGE_VERSION } from "./constants";

/**
 * Create and initialize a pyjs runtime (wasm32).
 *
 * ```js
 * const pyjs = await initializePyjsRuntime({ packages: ["numpy"] });
 * pyjs.runPython("import numpy");
 * ```
 */
export function initializePyjsRuntime(options?: IInitializeOptions): Promise<PyjsModule> {
  return initialize("wasm32", options);
}

/**
 * Compile the runtime wasm once, e.g. in the main thread, and post it to
 * workers: `initializePyjsRuntime({ wasmModule })` (no second compile).
 */
export function compileRuntime(options?: IAssetsOptions): Promise<WebAssembly.Module> {
  return compile("wasm32", options);
}

export default initializePyjsRuntime;
