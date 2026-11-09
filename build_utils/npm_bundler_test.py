"""Does the npm package work in apps built with the common bundlers?

For each bundler a minimal app is generated in build_root/npm/bundler_test/<bundler>/
which installs the locally built package (`npm install <tgz>`, like a user
would), imports it with a bare specifier and is built with the bundler's
default production settings. Only the build output is served (like a
deployment) and checked in a headless browser: init, the Module API, the
stdlib and (--network) `installPackages`, which loads the lazy solver chunk.
Failed requests (e.g. 404 for the runtime / python tarballs) are reported:
they show where the package expected its assets.

Two ways to deploy the assets (runtime + python environment), both tested:

* selfhost: `npx <package> copy-assets dist/pyjs` after the build, the app
  passes `assetsUrl: "pyjs/"` and `cdnFallback: false`
* cdn: default options, the assets are not next to the bundled module, so the
  package falls back to the CDN. `cdnUrl` points to a local route serving the
  package's assets instead of jsDelivr (the package is not published yet).

Usage: python npm_bundler_test.py <package .tgz> [--bundlers vite webpack rollup esbuild parcel]
           [--browser chromium] [--network] [--keep-going]
"""

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

from playwright.async_api import async_playwright

from npm_smoke_test import serve

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "build_root" / "npm" / "bundler_test"
TIMEOUT_MS = 600_000

BUNDLER_DEPS = {
    "vite": {"vite": "8.3.7"},
    "webpack": {"webpack": "5.112.2", "webpack-cli": "7.3.1"},
    "rollup": {"rollup": "4.68.2", "@rollup/plugin-node-resolve": "16.0.3"},
    "esbuild": {"esbuild": "0.28.2"},
    "parcel": {"parcel": "2.16.4"},
}

MAIN_JS = """\
import { initializePyjsRuntime } from "@PKG@";

const params = new URLSearchParams(location.search);

function check(checks, name, actual, expected) {
  checks.push({ name, ok: JSON.stringify(actual) === JSON.stringify(expected), actual, expected });
}

async function main() {
  const checks = [];
  const output = [];
  try {
    const options = { print: (t) => output.push(t), printErr: (t) => output.push(t) };
    if (params.get("mode") === "selfhost") {
      options.assetsUrl = new URL("pyjs/", location.href).href;
      options.cdnFallback = false;
    } else if (params.get("cdn")) {
      options.cdnUrl = params.get("cdn");
    }
    const pyjs = await initializePyjsRuntime(options);
    check(checks, "eval", pyjs.eval("40 + 2"), 42);
    check(checks, "exec_eval", pyjs.exec_eval("x = 20\\nx * 2 + 2"), 42);
    check(checks, "stdlib", pyjs.exec_eval("import json\\njson.dumps([1])"), "[1]");
    check(checks, "pyjs", pyjs.exec_eval("import pyjs\\nint(pyjs.js.Math.max(41, 42))"), 42);
    if (params.get("network") === "1") {
      const installed = await pyjs.installPackages(["six"]);
      check(checks, "installPackages six", installed.includes("six"), true);
      check(checks, "import six", pyjs.exec_eval("import six\\nsix.__name__"), "six");
    }
    window.__result = { ok: checks.every((c) => c.ok), checks, output };
  } catch (e) {
    const msg = e && typeof e === "object" && "has_err" in e ? `python error: ${e.message} ${e.error}` : String((e && e.stack) || e);
    window.__result = { ok: false, checks, output, error: msg };
  }
}
main();
"""

INDEX_HTML = """\
<!doctype html>
<html>
<head><meta charset="utf-8"><title>pyjs @BUNDLER@ test</title></head>
<body>
<script type="module" src="@SRC@"></script>
</body>
</html>
"""

WEBPACK_CONFIG = """\
const path = require("path");
module.exports = {
  mode: "production",
  entry: "./src/main.js",
  output: { path: path.resolve(__dirname, "dist"), filename: "main.js", clean: true },
};
"""

ROLLUP_CONFIG = """\
import { nodeResolve } from "@rollup/plugin-node-resolve";
export default {
  input: "src/main.js",
  output: { dir: "dist", format: "es" },
  plugins: [nodeResolve({ browser: true })],
};
"""


def package_name(tgz):
    with tarfile.open(tgz) as tar:
        return json.load(tar.extractfile("package/package.json"))["name"]


def write_project(bundler, tgz, name):
    project = WORK / bundler
    # keep node_modules of the bundler between runs, always reinstall the package
    for entry in ["src", "dist", ".parcel-cache", "index.html", "package.json", "package-lock.json"]:
        p = project / entry
        if p.is_dir():
            shutil.rmtree(p)
        elif p.exists():
            p.unlink()
    shutil.rmtree(project / "node_modules" / name, ignore_errors=True)
    (project / "src").mkdir(parents=True)
    (project / "src" / "main.js").write_text(MAIN_JS.replace("@PKG@", name))

    scripts = {
        "vite": "vite build",
        "webpack": "webpack --config webpack.config.cjs",
        "rollup": "rollup -c rollup.config.mjs",
        "esbuild": "esbuild src/main.js --bundle --format=esm --splitting --outdir=dist",
        "parcel": "parcel build index.html --dist-dir dist --no-cache",
    }
    package = {
        "name": f"pyjs-{bundler}-test",
        "private": True,
        "type": "module",
        "scripts": {"build": scripts[bundler]},
        "dependencies": {name: f"file:{tgz}"},
        "devDependencies": BUNDLER_DEPS[bundler],
    }
    if bundler == "parcel":
        package["source"] = "index.html"
        del package["type"]  # parcel: html entry
    (project / "package.json").write_text(json.dumps(package, indent=2))

    # index.html: the bundler's entry (vite, parcel) or copied next to the output
    src = {"vite": "/src/main.js", "parcel": "./src/main.js"}.get(bundler, "./main.js")
    html = INDEX_HTML.replace("@BUNDLER@", bundler).replace("@SRC@", src)
    (project / "index.html").write_text(html)
    if bundler == "webpack":
        (project / "webpack.config.cjs").write_text(WEBPACK_CONFIG)
    if bundler == "rollup":
        (project / "rollup.config.mjs").write_text(ROLLUP_CONFIG)
    return project


def run(cmd, cwd, log):
    with open(log, "a") as f:
        f.write(f"\n$ {' '.join(cmd)}\n")
        f.flush()
        return subprocess.run(cmd, cwd=cwd, stdout=f, stderr=subprocess.STDOUT).returncode


def build(bundler, project):
    log = project / "build.log"
    log.write_text("")
    if run(["npm", "install", "--no-audit", "--no-fund"], project, log) != 0:
        return False, log
    if run(["npm", "run", "build"], project, log) != 0:
        return False, log
    dist = project / "dist"
    if bundler in ("webpack", "rollup", "esbuild"):
        shutil.copy(project / "index.html", dist / "index.html")
    # self-hosted assets, like a user would deploy them
    if run(["npx", "--no-install", "pyjs", "copy-assets", "dist/pyjs"], project, log) != 0:
        return False, log
    return (dist / "index.html").exists(), log


async def check(browser, dist, cdn_dir, mode, network):
    # /cdn: stands in for jsDelivr (the package's assets)
    server, base = serve({"/cdn": cdn_dir, "/": dist})
    page = await browser.new_page()
    failed = []
    console = []
    page.on("response", lambda r: failed.append(f"{r.status} {r.url[len(base):]}") if r.status >= 400 else None)
    page.on("requestfailed", lambda r: failed.append(f"failed {r.url[len(base):]}"))
    page.on("console", lambda m: console.append(f"[{m.type}] {m.text}"))
    page.on("pageerror", lambda e: console.append(f"[pageerror] {e}"))
    try:
        query = f"mode={mode}&network={'1' if network else '0'}"
        if mode == "cdn":
            query += f"&cdn={base}/cdn/"
        await page.goto(f"{base}/index.html?{query}")
        try:
            await page.wait_for_function("() => window.__result !== undefined", timeout=TIMEOUT_MS)
            result = await page.evaluate("() => window.__result")
        except Exception as e:
            result = {"ok": False, "error": f"no result: {e}"}
        return result, failed, console
    finally:
        await page.close()
        server.shutdown()


async def main(tgz, bundlers, browser_name, network):
    tgz = Path(tgz).resolve()
    name = package_name(tgz)
    WORK.mkdir(parents=True, exist_ok=True)
    summary = []
    async with async_playwright() as p:
        browser = await getattr(p, browser_name).launch()
        try:
            for bundler in bundlers:
                print(f"=== {bundler}", flush=True)
                project = write_project(bundler, tgz, name)
                ok_build, log = build(bundler, project)
                if not ok_build:
                    print(f"  BUILD FAILED, log: {log}")
                    print("    " + "\n    ".join(log.read_text().splitlines()[-25:]))
                    summary.append((bundler, "build failed"))
                    continue
                cdn_dir = project / "node_modules" / name / "assets"
                for mode in ("selfhost", "cdn"):
                    print(f"  -- {mode}", flush=True)
                    result, failed, console = await check(browser, project / "dist", cdn_dir, mode, network)
                    for c in result.get("checks", []):
                        print(f"    {'ok  ' if c['ok'] else 'FAIL'} {c['name']}")
                    if not result.get("ok"):
                        print(f"    error: {result.get('error')}")
                    # in cdn mode the probe of the module-relative location fails by design
                    if failed and not result.get("ok"):
                        print("    failed requests:", *sorted(set(failed))[:20], sep="\n      ")
                        print("    console (last 15):", *console[-15:], sep="\n      ")
                    summary.append((f"{bundler} / {mode}", "PASSED" if result.get("ok") else "FAILED"))
        finally:
            await browser.close()
    print("\nbundler test summary:")
    for bundler, status in summary:
        print(f"  {status:12} {bundler}")
    return all(status == "PASSED" for _, status in summary)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("tgz")
    parser.add_argument("--bundlers", nargs="+", default=list(BUNDLER_DEPS))
    parser.add_argument("--browser", default="chromium", choices=["chromium", "firefox", "webkit"])
    parser.add_argument("--network", action="store_true")
    args = parser.parse_args()
    ok = asyncio.run(main(args.tgz, args.bundlers, args.browser, args.network))
    sys.exit(0 if ok else 1)
