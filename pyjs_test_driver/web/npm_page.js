// page.js of the npm page: pyjs from the npm package (copied to ./pyjs/),
// the test packages are installed at runtime via mambajs (extraPackages).
// @ENTRY@ / @PACKAGES@ are filled in by `pyjs_test_driver build-page npm`.
import { initializePyjsRuntime } from "./pyjs/dist/@ENTRY@.js";

const PACKAGES = @PACKAGES@;

/** an initialized pyjs (the env of the package + the test packages) */
export async function createPyjs(options) {
  return initializePyjsRuntime({ extraPackages: PACKAGES, preloadSharedLibs: options.preload });
}
