// The test harness shared by every page: given a function that brings up an
// initialized pyjs, it writes the test suite (tests/ or benchmarks/, served
// by the driver) into the emscripten file system and awaits its
// `main(options)` (tests/main.py, benchmarks/main.py). Pages only differ in
// how they create pyjs (page.js: vanilla runtime, npm package, bundled app).

/** the options of a run: the query string of the page (set by the driver) */
export function optionsFromUrl(search = globalThis.location.search) {
  const params = Object.fromEntries(new URLSearchParams(search));
  const flag = (name, dflt) => (params[name] === undefined ? dflt : params[name] === "1");
  return {
    ...params,
    entry: params.entry ?? "tests",
    disable_jspi: flag("disable_jspi", false),
    // undefined: the default of the page (npm: preload in the main thread only)
    preload: flag("preload", undefined),
  };
}

/** a readable message for errors thrown by JS or (as {has_err, ...}) by python */
function errorText(e) {
  if (e && typeof e === "object" && "has_err" in e) {
    return `python error: ${e.message ?? ""} ${e.error ?? ""}`.trim();
  }
  return String((e && e.stack) || e);
}

/** copy the suite dir (file list: <suite>/__files__.json, by the driver) to /<entry> */
async function writeSuite(pyjs, suiteUrl, entry) {
  const files = await (await fetch(`${suiteUrl}/__files__.json`)).json();
  await Promise.all(
    files.map(async (file) => {
      const data = new Uint8Array(await (await fetch(`${suiteUrl}/${file}`)).arrayBuffer());
      const path = `/${entry}/${file}`;
      pyjs.FS.mkdirTree(path.slice(0, path.lastIndexOf("/")));
      pyjs.FS.writeFile(path, data);
    })
  );
}

/** create pyjs, run the suite, return its result (`{ok, ...}`); never throws */
export async function runSuite(createPyjs, options) {
  try {
    const pyjs = await createPyjs(options);
    // the JS tests (tests/js) get the Module from here
    globalThis.pyjs = pyjs;
    const suiteUrl = new URL(`/${options.entry}`, globalThis.location.href).href;
    await writeSuite(pyjs, suiteUrl, options.entry);
    const suiteOptions = JSON.stringify({ ...options, tests_url: suiteUrl });
    const resultJson = await pyjs.async_exec_eval(
      `import json, sys\n` +
        `sys.path.insert(0, "/${options.entry}")\n` +
        `import main as _suite_main\n` +
        `json.dumps(await _suite_main.main(json.loads(${JSON.stringify(suiteOptions)})))`
    );
    return JSON.parse(resultJson);
  } catch (e) {
    console.error(errorText(e));
    return { ok: false, error: errorText(e) };
  }
}
