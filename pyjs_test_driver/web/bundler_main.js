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
    packages: PACKAGES,
    // like the npm page: a pinned package at init (the default entry: wasm32)
    urls: ["/test-channel/emscripten-wasm32/pyjs-test-channel-arch-1.0.0-0.tar.bz2"],
    files: [{ path: "/files_at_init/hello.txt", data: "hello from files" }],
    // tests/npm/test_archives.py: an archive unpacked before python starts
    archives: [{ url: "/test-data/archive_init.tar.gz", path: "/unpacked_at_init" }],
    preloadSharedLibs: options.preload,
    cdnUrl: new URL("pyjs/", globalThis.location.href).href,
  });
}

runSuite(createPyjs, optionsFromUrl()).then((result) => {
  window.__pyjs_result = result;
});
