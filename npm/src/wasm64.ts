/** pyjs runtime for wasm64 (memory64, needs a browser with memory64 support). */
import { compileRuntime as compile, initialize } from "./runtime";
import type { IAssetsOptions, IInitializeOptions, PyjsModule } from "./types";

export * from "./types";
export { DEFAULT_CHANNELS, DEFAULT_CDN_URL, PACKAGE_NAME, PACKAGE_VERSION } from "./constants";

/**
 * Create and initialize a pyjs runtime (wasm64).
 *
 * ```js
 * const pyjs = await initializePyjsRuntime({ packages: ["numpy"] });
 * pyjs.runPython("import numpy");
 * ```
 */
export function initializePyjsRuntime(options?: IInitializeOptions): Promise<PyjsModule> {
  return initialize("wasm64", options);
}

/**
 * Compile the runtime wasm once, e.g. in the main thread, and post it to
 * workers: `initializePyjsRuntime({ wasmModule })` (no second compile).
 */
export function compileRuntime(options?: IAssetsOptions): Promise<WebAssembly.Module> {
  return compile("wasm64", options);
}

export default initializePyjsRuntime;
