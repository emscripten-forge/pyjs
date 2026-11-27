// page.js of the pyodide page: pyodide instead of pyjs, to run the benchmarks
// on the reference pyjs is compared with. pyodide is loaded from ./pyodide/,
// a local copy of a release next to this file (`pyjs_test_driver build-page
// pyodide` puts it there), so a run does not depend on a CDN.
// Only what the harness needs is provided (`FS`, `runPythonAsync`).
// @PACKAGES@ is filled in by `pyjs_test_driver build-page pyodide`.
import { loadPyodide } from "./pyodide/pyodide.mjs";

const PACKAGES = @PACKAGES@;

/** pyodide behind the part of the pyjs Module API the harness uses */
export async function createPyjs(options) {
  // indexURL: where pyodide finds its runtime, standard library and packages
  const pyodide = await loadPyodide({ indexURL: new URL("./pyodide/", import.meta.url).href });
  if (PACKAGES.length) {
    await pyodide.loadPackage(PACKAGES);
  }
  return {
    FS: pyodide.FS,
    runPythonAsync: (code) => pyodide.runPythonAsync(code),
  };
}
