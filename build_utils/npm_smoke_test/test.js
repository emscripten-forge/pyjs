// The checks of the npm smoke test (build_utils/npm_smoke_test.py), run in the
// main thread or in a module worker. The package is imported from a different
// path than this file (like from a CDN): the assets must be found via the
// `import.meta.url` of the package.
function check(checks, name, actual, expected) {
  const ok = JSON.stringify(actual) === JSON.stringify(expected);
  checks.push({ name, ok, actual, expected });
}

function pyErr(e) {
  // python errors are thrown as {has_err, message, error, redirect_error}
  if (e && typeof e === "object" && "has_err" in e) {
    return `python error: ${e.message ?? ""} ${e.error ?? ""}`;
  }
  return String((e && e.stack) || e);
}

export async function run(params) {
  const entry = params.entry ?? "index";
  const network = params.network === "1";
  const pkg = params.pkg;
  const expectedArch = entry === "wasm64" ? "wasm64" : "wasm32";
  const checks = [];
  const output = [];
  try {
    const mod = await import(`${pkg}/dist/${entry}.js`);
    check(checks, "default export", mod.default === mod.initializePyjsRuntime, true);
    const pyjs = await mod.initializePyjsRuntime({
      extraPackages: network ? ["numpy"] : [],
      print: (text) => output.push(text),
      printErr: (text) => output.push(text),
    });

    check(checks, "pyjsArch", pyjs.pyjsArch, expectedArch);
    check(checks, "python version", pyjs.pythonVersion.slice(0, 2), [3, 14]);
    // the existing Module API (exec / eval / exec_eval / async_exec_eval / to_js)
    check(checks, "eval", pyjs.eval("40 + 2"), 42);
    pyjs.exec("value = 'from exec'");
    check(checks, "exec", pyjs.eval("value"), "from exec");
    check(checks, "exec_eval", pyjs.exec_eval("x = 20\nx * 2 + 2"), 42);
    check(
      checks,
      "async_exec_eval",
      await pyjs.async_exec_eval("import asyncio\nawait asyncio.sleep(0)\n'awaited'"),
      "awaited"
    );
    check(checks, "pointer size", pyjs.exec_eval("import sys\n8 if sys.maxsize > 2**32 else 4"), expectedArch === "wasm64" ? 8 : 4);
    const list = pyjs.eval("[1, 2, 3]");
    const jsList = pyjs.to_js(list);
    check(checks, "to_js", Array.from(jsList), [1, 2, 3]);
    list.delete?.();
    check(
      checks,
      "pyjs module + js",
      pyjs.exec_eval("import pyjs\nint(pyjs.js.Function('a', 'b', 'return a + b')(40, 2))"),
      42
    );
    check(checks, "stdlib", pyjs.exec_eval("import json, decimal, sqlite3\njson.dumps({'a': 1})"), '{"a": 1}');
    check(checks, "stdout", (pyjs.exec("print('hello stdout')"), output.includes("hello stdout")), true);

    const info = {
      jspi: pyjs.eval("__import__('pyjs').jspi_enabled()"),
      python: pyjs.pythonVersion.join("."),
    };

    if (network) {
      check(checks, "extraPackages numpy", pyjs.exec_eval("import numpy as np\nint(np.arange(10).sum())"), 45);
      const installed = await pyjs.installPackages(["six"]);
      check(checks, "installPackages returns six", installed.includes("six"), true);
      check(checks, "installPackages six", pyjs.exec_eval("import six\nsix.__name__"), "six");
      // already installed: nothing to do
      check(checks, "installPackages again", await pyjs.installPackages(["six"]), []);
    }
    return { ok: checks.every((c) => c.ok), checks, info, output: output.slice(-20) };
  } catch (e) {
    return { ok: false, checks, error: pyErr(e), output: output.slice(-40) };
  }
}
