// Entry of the bundler pages (main thread only): the npm package imported by
// its bare name (resolved + bundled by the bundler under test) and the shared
// harness. @PKG@ / @PACKAGES@ are filled in by `build-page <bundler>`.
import { initializePyjsRuntime } from "@PKG@";
import { optionsFromUrl, runSuite } from "./harness.js";

const PACKAGES = @PACKAGES@;

/** an initialized pyjs; bundlers do not copy the runtime files: they are in
 * ./pyjs/ (`npx <pkg> copy-assets`) and found via the CDN fallback (cdnUrl) */
async function createPyjs(options) {
  return initializePyjsRuntime({
    extraPackages: PACKAGES,
    preloadSharedLibs: options.preload,
    cdnUrl: new URL("pyjs/", globalThis.location.href).href,
  });
}

runSuite(createPyjs, optionsFromUrl()).then((result) => {
  window.__pyjs_result = result;
});
