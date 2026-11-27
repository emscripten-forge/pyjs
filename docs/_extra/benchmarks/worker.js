// Runs the benchmarks of the pyjs repository (benchmarks/, copied next to the
// docs by docs/conf.py) with one runtime, in this worker: pyjs (the npm
// package deployed next to the docs) or pyodide (the reference, from its CDN).
// One worker per runtime and run (the page terminates it afterwards): the two
// runtimes never share memory or JIT state.
//
// message in:  {runtime: "pyjs" | "pyodide", pyjsEntry, pyodideUrl, suiteUrl, options}
// messages out: {log, error?} (python's output), {status} (what happens now),
//               {result} (benchmarks/main.py's dict) or {failed} (an exception)

/** pyjs from the npm package: `entry` is its dist/index.js (wasm32) or dist/wasm64.js */
async function loadPyjs(entry, print, printErr) {
  const { initializePyjsRuntime } = await import(entry);
  const pyjs = await initializePyjsRuntime({ print, printErr });
  return { FS: pyjs.FS, runPythonAsync: (code) => pyjs.runPythonAsync(code) };
}

/** pyodide from its CDN: `url` is the release dir (…/full/) */
async function loadPyodideRuntime(url, print, printErr) {
  const { loadPyodide } = await import(`${url}pyodide.mjs`);
  const pyodide = await loadPyodide({ indexURL: url, stdout: print, stderr: printErr });
  return { FS: pyodide.FS, runPythonAsync: (code) => pyodide.runPythonAsync(code) };
}

/** the suite files (list: files.json, written by docs/conf.py) into /benchmarks */
async function writeSuite(runtime, suiteUrl) {
  const files = await (await fetch(`${suiteUrl}files.json`)).json();
  runtime.FS.mkdirTree("/benchmarks");
  await Promise.all(
    files.map(async (file) => {
      const data = new Uint8Array(await (await fetch(`${suiteUrl}${file}`)).arrayBuffer());
      runtime.FS.writeFile(`/benchmarks/${file}`, data);
    }),
  );
}

self.onmessage = async ({ data }) => {
  const print = (text) => self.postMessage({ log: String(text) });
  const printErr = (text) => self.postMessage({ log: String(text), error: true });
  try {
    self.postMessage({ status: `loading ${data.runtime}…` });
    const runtime =
      data.runtime === "pyjs"
        ? await loadPyjs(data.pyjsEntry, print, printErr)
        : await loadPyodideRuntime(data.pyodideUrl, print, printErr);
    await writeSuite(runtime, data.suiteUrl);
    self.postMessage({ status: `running the benchmarks on ${data.runtime}…` });
    const resultJson = await runtime.runPythonAsync(
      `import json, sys\n` +
        `sys.path.insert(0, "/benchmarks")\n` +
        `import main as _bench_main\n` +
        `json.dumps(await _bench_main.main(json.loads(${JSON.stringify(JSON.stringify(data.options))})))`,
    );
    self.postMessage({ result: JSON.parse(resultJson) });
  } catch (e) {
    // (a python exception: its message is the traceback)
    self.postMessage({ failed: String((e && (e.message || e.stack)) || e) });
  }
};
