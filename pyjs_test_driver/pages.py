"""`build-page`: create the page dirs `run` can test.

Every page dir fulfills the page contract (see driver.py): an `index.html`
that brings up pyjs and runs the suite with the shared `web/harness.js`.
The kinds only differ in how pyjs is created:

* vanilla: the raw emscripten output + an empack-packed env (the classic
  Module API, how projects using pyjs as a static library load it)
* npm: the npm package (test packages installed at runtime via mambajs)
* vite / webpack / rollup / esbuild / parcel: an app built with that bundler
  around the npm package (main thread only)
"""

import json
import os
import shutil
import subprocess
import tarfile
from pathlib import Path

WEB = Path(__file__).resolve().parent / "web"
# files of the vanilla / npm pages (bundler pages bundle their own entry)
CONTRACT_FILES = ["index.html", "harness.js", "worker.js"]

BUNDLERS = {
    "vite": {"deps": {"vite": "8.3.7"}, "build": "vite build"},
    "webpack": {
        "deps": {"webpack": "5.112.2", "webpack-cli": "7.3.1"},
        "build": "webpack --config webpack.config.cjs",
    },
    "rollup": {
        "deps": {"rollup": "4.68.2", "@rollup/plugin-node-resolve": "16.0.3"},
        "build": "rollup -c rollup.config.mjs",
    },
    "esbuild": {
        "deps": {"esbuild": "0.28.2"},
        "build": "esbuild src/main.js --bundle --format=esm --splitting --outdir=dist",
    },
    "parcel": {"deps": {"parcel": "2.16.4"}, "build": "parcel build index.html --dist-dir dist --no-cache"},
}

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

BUNDLER_INDEX_HTML = """\
<!doctype html>
<html>
<head><meta charset="utf-8"><title>pyjs test page (@BUNDLER@)</title></head>
<body><script type="module" src="@SRC@"></script></body>
</html>
"""


def fresh_dir(path):
    """an empty dir at `path`"""
    path = Path(path)
    shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True)
    return path


def copy_contract_files(out, page_js):
    """index.html / harness.js / worker.js + the page's own page.js"""
    for name in CONTRACT_FILES:
        shutil.copy(WEB / name, out / name)
    (out / "page.js").write_text(page_js)


def build_vanilla(out, assets):
    """page from `assets`: pyjs_runtime_browser.{js,wasm} + an empack-packed env"""
    out = fresh_dir(out)
    shutil.copytree(assets, out, dirs_exist_ok=True)
    copy_contract_files(out, (WEB / "vanilla_page.js").read_text())


def build_npm(out, package, arch, packages):
    """page from the npm package dir (copied to pyjs/), entry of `arch`"""
    out = fresh_dir(out)
    shutil.copytree(package, out / "pyjs")
    # wasm32 via the default entry of the package
    entry = "index" if arch == "wasm32" else arch
    page_js = (WEB / "npm_page.js").read_text()
    page_js = page_js.replace("@ENTRY@", entry).replace("@PACKAGES@", json.dumps(packages))
    copy_contract_files(out, page_js)


def build_bundler(bundler, out, tgz, packages, work_dir):
    """page = the output of `bundler` for an app around the npm package (`tgz`)"""
    tgz = Path(tgz).resolve()
    with tarfile.open(tgz) as tar:
        name = json.load(tar.extractfile("package/package.json"))["name"]

    # the project of the app (node_modules of the bundler are kept between runs)
    project = Path(work_dir) / bundler
    project.mkdir(parents=True, exist_ok=True)
    for entry in ["src", "dist", ".parcel-cache", "package-lock.json"]:
        path = project / entry
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)
    shutil.rmtree(project / "node_modules" / name, ignore_errors=True)
    (project / "src").mkdir()
    main_js = (WEB / "bundler_main.js").read_text()
    main_js = main_js.replace("@PKG@", name).replace("@PACKAGES@", json.dumps(packages))
    (project / "src" / "main.js").write_text(main_js)
    shutil.copy(WEB / "harness.js", project / "src" / "harness.js")

    package_json = {
        "name": f"pyjs-test-page-{bundler}",
        "private": True,
        "type": "module",
        "scripts": {"build": BUNDLERS[bundler]["build"]},
        "dependencies": {name: f"file:{tgz}"},
        "devDependencies": BUNDLERS[bundler]["deps"],
    }
    if bundler == "parcel":
        package_json["source"] = "index.html"
        del package_json["type"]  # parcel: html entry
    (project / "package.json").write_text(json.dumps(package_json, indent=2))
    # vite / parcel: index.html is the entry; the others: copied next to the output
    src = {"vite": "/src/main.js", "parcel": "./src/main.js"}.get(bundler, "./main.js")
    (project / "index.html").write_text(
        BUNDLER_INDEX_HTML.replace("@BUNDLER@", bundler).replace("@SRC@", src)
    )
    if bundler == "webpack":
        (project / "webpack.config.cjs").write_text(WEBPACK_CONFIG)
    if bundler == "rollup":
        (project / "rollup.config.mjs").write_text(ROLLUP_CONFIG)

    log = project / "build.log"
    log.write_text("")
    npm_run(["npm", "install", "--no-audit", "--no-fund"], project, log)
    npm_run(["npm", "run", "build"], project, log)
    dist = project / "dist"
    if not (dist / "index.html").exists():
        shutil.copy(project / "index.html", dist / "index.html")
    # the runtime files, deployed like a user would (see bundler_main.js)
    npm_run(["npx", "--no-install", "pyjs", "copy-assets", "dist/pyjs"], project, log)

    out = fresh_dir(out)
    shutil.copytree(dist, out, dirs_exist_ok=True)


def npm_run(cmd, cwd, log):
    """run a node tool for a bundler page, output to `log`, raise on failure"""
    # CI=true: like on CI (e.g. parcel does not auto install node polyfills)
    env = {**os.environ, "CI": "true"}
    with open(log, "a") as f:
        f.write(f"\n$ {' '.join(cmd)}\n")
        f.flush()
        ret = subprocess.run(cmd, cwd=cwd, stdout=f, stderr=subprocess.STDOUT, env=env).returncode
    if ret != 0:
        tail = "\n".join(Path(log).read_text().splitlines()[-30:])
        raise RuntimeError(f"`{' '.join(cmd)}` failed in {cwd}:\n{tail}")
