/** pyjs runtime for wasm64 (memory64, needs a browser with memory64 support). */
import { initialize } from "./runtime";
import type { IInitializeOptions, PyjsModule } from "./types";

export * from "./types";
export { DEFAULT_CHANNELS, DEFAULT_CDN_URL, PACKAGE_NAME, PACKAGE_VERSION } from "./constants";

/**
 * Create and initialize a pyjs runtime (wasm64).
 *
 * ```js
 * const pyjs = await initializePyjsRuntime({ extraPackages: ["numpy"] });
 * pyjs.exec("import numpy");
 * ```
 */
export function initializePyjsRuntime(options?: IInitializeOptions): Promise<PyjsModule> {
  return initialize("wasm64", options);
}

export default initializePyjsRuntime;
