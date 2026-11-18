// page.js of the npm page: pyjs from the npm package (copied to ./pyjs/),
// the test packages are solved and installed at runtime (option `packages`).
// @ENTRY@ / @PACKAGES@ are filled in by `pyjs_test_driver build-page npm`.
import { initializePyjsRuntime } from "./pyjs/dist/@ENTRY@.js";

const PACKAGES = @PACKAGES@;

/** progress events of the initialization (tests/npm/test_install.py) */
globalThis.__pyjs_progress = [];

/** an initialized pyjs (the env of the package + the test packages) */
export async function createPyjs(options) {
  const arch = "@ENTRY@" === "wasm64" ? "wasm64" : "wasm32";
  return initializePyjsRuntime({
    packages: PACKAGES,
    preloadSharedLibs: options.preload,
    // tests/npm/test_install.py: a pinned package (no solver) from the
    // driver's test channel, installed together with the solved ones
    urls: [`/test-channel/emscripten-${arch}/pyjs-test-channel-arch-1.0.0-0.tar.bz2`],
    // tests/npm/test_archives.py: an archive unpacked before python starts
    archives: [{ url: "/test-data/archive_init.tar.gz", path: "/unpacked_at_init" }],
    files: [{ path: "/files_at_init/hello.txt", data: "hello from files" }],
    onProgress: (p) => globalThis.__pyjs_progress.push(p),
  });
}
