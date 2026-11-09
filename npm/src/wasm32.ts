/** pyjs runtime for wasm32 (the default entry of the package). */
import { initialize } from "./runtime";
import type { IInitializeOptions, PyjsModule } from "./types";

export * from "./types";
export { DEFAULT_CHANNELS, DEFAULT_CDN_URL, PACKAGE_NAME, PACKAGE_VERSION } from "./constants";

/**
 * Create and initialize a pyjs runtime (wasm32).
 *
 * ```js
 * const pyjs = await initializePyjsRuntime({ extraPackages: ["numpy"] });
 * pyjs.exec("import numpy");
 * ```
 */
export function initializePyjsRuntime(options?: IInitializeOptions): Promise<PyjsModule> {
  return initialize("wasm32", options);
}

export default initializePyjsRuntime;
