# npm package

The quickest way to use pyjs in a web application: the npm package contains
the pyjs runtime for **wasm32** and **wasm64** together with Python, its
standard library and the `pyjs` Python module. Extra conda packages
(numpy, pandas, ... from emscripten-forge) are installed at runtime: either
solved from specs (with [mambajs](https://github.com/emscripten-forge/mambajs),
loaded only then) or pinned by URL (no solver at all, e.g. from `npx … lock`).
No conda environment, no `empack`, no server-side setup.

```{note}
The package is published as `@PYJS_NPM_PACKAGE@` for now; it will move to the
`@emscripten-forge` scope.
```

## Usage

```bash
npm install @PYJS_NPM_PACKAGE@
```

```js
// wasm32
import { initializePyjsRuntime } from "@PYJS_NPM_PACKAGE@";
// wasm64:
// import { initializePyjsRuntime } from "@PYJS_NPM_PACKAGE@/wasm64";

const pyjs = await initializePyjsRuntime({ packages: ["numpy"] });

pyjs.runPython("import numpy as np");
pyjs.runPython("int(np.arange(10).sum())");  // 45
pyjs.runPython("x = 2\nx * 21");             // 42
await pyjs.runPythonAsync(
  "import asyncio\nawait asyncio.sleep(0)\n'done'"
);                                            // "done"

// install more later (verbose: with the solver log)
await pyjs.installPackages(["regex"]);
await pyjs.installPackages(["scipy"], { verbose: true });
```

`initializePyjsRuntime` returns the pyjs runtime (the emscripten `Module`) with
the API described in {doc}`JavaScript_API` (`runPython`, `runPythonAsync`,
`pyimport`, `globals`, `toPy`, `FS`, ...), plus `installPackages`,
`unpackArchive`, `addFiles` and `saveBytecode`.

Without a bundler, the package can be imported directly from a CDN, see [CDN](cdn.md).

### Optional parts of the stdlib

The extension modules `_ssl`, `_sqlite3`, `_lzma` and the CJK codecs (with
their C libraries: openssl, sqlite, xz) are shipped with the package, but not
installed by default: most programs do not need them, and they are the
largest part of the stdlib. Ask for them at the start or later (no download
from a channel, they come from the package itself):

```js
const pyjs = await initializePyjsRuntime({ stdlib: ["sqlite3", "ssl"] }); // or "all"
await pyjs.installPackages(["lzma"]);  // later ("python-lzma" works too)
```

Available: `ssl`, `sqlite3`, `lzma`, `cjkcodecs`, `test-modules` (CPython's
`_testcapi`, ...). Without them `import sqlite3` raises
`ModuleNotFoundError: No module named '_sqlite3'`. (With a python that has these
modules built in, `stdlib` does nothing.)

### What happens at the start

Everything that can run in parallel does: the runtime wasm is instantiated
while the specs are solved and while the python environment, the packages and
the archives download. Then the downloads are written into the file system in
a fixed order (the python environment, packages, `archives`, `files`) by the
runtime's own extractor (libarchive: tar / zip, gzip / bzip2 / zstd, conda
`.tar.bz2` and `.conda`), Python starts, and the shared libraries of the
packages are loaded (main thread). `pyjs.initTimings` shows where the time went
(ms): waiting for the runtime / downloads / the solver, extracting, starting,
linking. `pyjs.installTimings` does the same for the last `installPackages`
call (`solve`, `waitDownloads`, `extractPackages`, `link`, `invalidateCaches`,
`total`).

## Pinned packages: no solver in the browser

Solving needs the channels' repodata (several MB, on every visit) and the
solver itself. For a fixed set of packages, solve once at build time:

```bash
npx @PYJS_NPM_PACKAGE@ lock numpy pandas -o pyjs-lock.json
# only one architecture, other channels:
npx @PYJS_NPM_PACKAGE@ lock numpy --arch wasm32 --channel https://repo.prefix.dev/emscripten-forge/6x
```

`pyjs-lock.json` lists the packages per architecture (`{ "wasm32": [{url, sha256}], ... }`),
solved against the python environment of the installed package version:

```js
import lock from "./pyjs-lock.json" with { type: "json" };
const pyjs = await initializePyjsRuntime({ urls: lock.wasm32 });
```

`urls` also takes plain URL strings of conda packages (`.conda` / `.tar.bz2`);
name, version and build are taken from the file name. `installPackages`
accepts both, specs and pinned packages.

## Caching, checks, progress

* **Package cache:** installed conda packages are kept in Cache Storage
  (`pyjs-packages-v2`, keyed by URL: package URLs are immutable) as their
  final layout, an uncompressed tar. A second visit only untars them: no
  download, no bzip2 / zstd, no conda handling (numpy + scipy + pandas +
  matplotlib: unpacking 2.1 s -> 0.08 s). With pinned packages it needs no
  network for them at all. `cache: false` turns it off, `cache: "name"` uses
  another cache. Browsers may evict the cache under storage pressure; apps
  can ask for persistent storage with `navigator.storage.persist()`.
* **Bytecode cache:** python's `__pycache__/*.pyc` files of the packages and
  of the python environment are kept too (`<cache name>-bytecode`, by package
  URL) and come back with the package, so imports do not compile the sources
  again (the imports above: 2.2 s -> 0.5 s, python's start 0.36 s -> 0.09 s).
  **Saving is up to the app:** call `await pyjs.saveBytecode()` once the
  imports are done (it stores only what python wrote since the last save;
  await it before a reload). Nothing saves periodically; the only automatic
  save is a best-effort one when the page becomes hidden (main thread only: a
  closing page may be gone before the write completes; workers must call
  `saveBytecode()` themselves).

  ```js
  pyjs.runPython("import numpy, scipy.linalg");
  await pyjs.saveBytecode();
  ```

  Restoring is automatic (with the package).
  Python checks each `.pyc` against the modification time + size of its
  source (kept from the archive), a stale one is compiled again.
  `bytecodeCache: false` turns it off. So does python itself when it writes
  no bytecode: `sys.dont_write_bytecode = True` / `PYTHONDONTWRITEBYTECODE`
  (also `PYTHONPYCACHEPREFIX` moves the files out of reach). Code edited at
  runtime needs neither: delete the edited files' `.pyc` before re-importing
  (`importlib.util.cache_from_source(path)`), python also recompiles when the
  source's mtime or size changed.
* **Archives** are not cached by default (an archive URL may change its
  content). `{url, path, cache: true}` caches one like a package: its
  unpacked files and the bytecode of its `.py` files, by URL + `path`. Only
  for URLs whose content never changes, e.g. with a content hash in the file
  name: a cached archive is not downloaded again.
* **sha256:** not checked by default (hashing large packages costs time);
  `verifySha256: true` checks every package / archive that has a `sha256`
  (such packages are then always downloaded: the cached layout cannot be
  checked against the hash of the package file).
* **Progress:** `onProgress({item, phase, done, total})` with the phases
  `solve`, `download` (bytes), `cached`, `extract`, `link`, `start`.

```js
const pyjs = await initializePyjsRuntime({
  urls: lock.wasm32,
  onProgress: ({ item, phase, done, total }) => console.log(item, phase, done, total),
});
```

### In a web worker

The package works in the main thread and in module workers
(`new Worker(url, { type: "module" })`). In a worker the shared libraries of
packages are not preloaded (`dlopen` can compile synchronously there).

Several workers: compile the runtime wasm once and post it to them, each
worker then instantiates it without compiling again:

```js
// main thread
import { compileRuntime } from "@PYJS_NPM_PACKAGE@";
const wasmModule = await compileRuntime();
worker.postMessage({ wasmModule });

// worker
const pyjs = await initializePyjsRuntime({ wasmModule: event.data.wasmModule });
```

### With a bundler (Vite, webpack, Rollup, esbuild, Parcel)

`import { initializePyjsRuntime } from "@PYJS_NPM_PACKAGE@"` works in bundled
apps. The runtime wasm and the python environment (`assets/`) are not
JavaScript modules, so bundlers do not copy them; two ways to deploy them:

* **default:** if the assets are not found next to the module, they are
  loaded from jsDelivr, exactly the installed package version (one
  `console.warn`). Nothing to configure.
* **self-hosted** (offline, own CDN, no third-party requests): copy them into
  the static folder of your app (`public/` with Vite / Parcel, the folder
  copied to the output with webpack / Rollup / esbuild) and pass its url:

  ```bash
  # both architectures
  npx @PYJS_NPM_PACKAGE@ copy-assets public/pyjs
  # only one
  npx @PYJS_NPM_PACKAGE@ copy-assets public/pyjs --arch wasm32
  ```
  ```js
  const pyjs = await initializePyjsRuntime({
    assetsUrl: "/pyjs/",
    cdnFallback: false,
  });
  ```

  Re-run `copy-assets` after updating the package (the JS and the wasm must
  match).

## Options

| option | default | |
|---|---|---|
| `packages` | `[]` | conda package specs, solved and installed before Python starts |
| `urls` | `[]` | pinned conda packages (`{url, sha256?}` or URL strings), no solver |
| `archives` | `[]` | archives (`{url, path, sha256?, cache?}`) unpacked before Python starts, see below |
| `files` | `[]` | files (`{path, data}` or `{path, url}`) written before Python starts |
| `channels` | emscripten-forge 6x, conda-forge | channels the specs are solved against (also self-hosted ones, see below) |
| `cache` | `true` | package cache in Cache Storage (`false`, or a cache name) |
| `bytecodeCache` | `true` (with `cache`) | keep python's `.pyc` files of the packages for the next visit (saved by `saveBytecode()`) |
| `verifySha256` | `false` | check the sha256 of packages / archives that have one |
| `onProgress` | | progress events (see above) |
| `wasmModule` | | the runtime wasm compiled already (`compileRuntime()`) |
| `env` | | extra environment variables of Python |
| `assetsUrl` | `assets/` next to the module | url of a self-hosted copy of `assets/` (`copy-assets`) |
| `cdnUrl` | jsDelivr, this exact version | where `assets/` is loaded from when not next to the module |
| `cdnFallback` | `true` | `false`: error instead of loading from `cdnUrl` |
| `preloadSharedLibs` | main thread: `true`, worker: `false` | preload the `.so` files of packages |
| `print` / `printErr` | `console.log` / `console.warn` | stdout / stderr |
| `logger`, `verbose` | silent | solver messages |
| `moduleOptions` | | extra properties of the emscripten Module |

## Your own packages and files

**Self-hosted conda packages**: the output directory of `rattler-build`
(`noarch/`, `emscripten-wasm32/`, ... with their `repodata.json`) is a conda
channel made of static files. Deploy it next to your page (e.g. on GitHub
Pages) and list it first: channels listed earlier have priority (your build
of a package wins over a published one), the other packages still come from
emscripten-forge:

```js
const pyjs = await initializePyjsRuntime({
  channels: [
    new URL("channel", location.href).href, // absolute url
    "https://repo.prefix.dev/emscripten-forge/6x",
    "conda-forge",
  ],
  packages: ["my-package"],
});
```

A single package file needs no channel at all: `urls: ["my-package-1.0-0.conda"]`.

**Files that are not a package** (python sources, data, a filtered package):
pack them as a (compressed) tar or zip archive, e.g.
`tar czf examples.tar.gz -C examples .`; pyjs unpacks it into the file system,
before Python starts or later. Single files go in with `files` / `addFiles`:

```js
const pyjs = await initializePyjsRuntime({
  archives: [{ url: "examples.tar.gz", path: "/examples" }],
  files: [{ path: "/config/settings.json", data: JSON.stringify({ debug: true }) }],
});
await pyjs.unpackArchive({ url: "more_data.tar.bz2", path: "/data" });
await pyjs.addFiles([{ path: "/data/extra.csv", url: "extra.csv" }]);
pyjs.runPython("import sys; sys.path.insert(0, '/examples')");
```

A filtered package (stripped of tests, headers, docs, ...) as an archive with
a content hash in its name gets the package caches with `cache: true`: a
small first download, and later visits only untar and load cached bytecode:

```js
archives: [{ url: "packages-3f9a1c2e.tar.gz", path: "/", cache: true }],
```

## wasm32 or wasm64?

wasm32 is the default and works in all browsers. wasm64 (memory64) allows
more than 4 GB of memory (pyjs is linked with up to 16 GB) but needs a
browser with memory64 support. Extra packages are taken from the matching
channel subdir (`emscripten-wasm32` / `emscripten-wasm64`).

## Changes in 6.0

* New FFI core (nanobind + TypeScript instead of pybind11 + embind), see
  {doc}`design`.
* The API follows PEP 818 and pyodide. JavaScript side: `runPython`,
  `runPythonAsync`, `pyimport`, `globals`, `toPy` replace `exec`, `eval`,
  `exec_eval`, `async_exec_eval`, `eval_file`; Python objects are `PyProxy`
  objects (`proxy(...)`, `proxy.get(key)`, `destroy()`) instead of
  `pyobject` (`py_call`, `delete()`). Python side: `JSProxy` replaces
  `JsValue`, `JSException` the `Js*Error` classes, `create_proxy` /
  `create_once_callable` the callable helpers; see {doc}`python_api`.
* `run_sync` (JSPI): any number of Python stacks can wait at the same time;
  `loop.run_until_complete` blocks where `can_run_sync()` is true.
* Optional stdlib parts (`stdlib` option), see above.

## Changes in 5.2

* The bytecode cache no longer saves every few seconds (that listed every
  `__pycache__` directory periodically, an unpredictable cost): it saves on
  `await pyjs.saveBytecode()` (call it once the imports are done) and, best
  effort, when the page becomes hidden.

## Changes in 5.1

* Archives can be cached like packages: `{url, path, cache: true}` (unpacked
  files + bytecode), see Caching above.

## Changes in 5.0

* `extraPackages` / `extra_packages` → `packages`.
* New: `urls` (pinned packages), `files`, `cache`, `bytecodeCache`,
  `verifySha256`, `onProgress`, `wasmModule` / `compileRuntime()`, `env`,
  `addFiles()`, `saveBytecode()`, `npx … lock`.
* untarjs is gone (no `assets/untarjs.wasm`): archives and packages are
  extracted by the runtime itself (libarchive), also `.conda` packages.
* The classic Module API for filling the file system
  (`bootstrap_from_empack_packed_environment`, `init_phase_1` / `init_phase_2`,
  `_untar`, `_install_conda_file`) is removed; projects using the runtime
  directly fill the file system themselves and call `startPython()`, see
  {doc}`cpp`.
