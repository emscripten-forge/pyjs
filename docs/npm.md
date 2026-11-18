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

pyjs.exec("import numpy as np");
pyjs.eval("int(np.arange(10).sum())");  // 45
pyjs.exec_eval("x = 2\nx * 21");        // 42
await pyjs.async_exec_eval(
  "import asyncio\nawait asyncio.sleep(0)\n'done'"
);

// install more later (verbose: with the solver log)
await pyjs.installPackages(["regex"]);
await pyjs.installPackages(["scipy"], { verbose: true });
```

`initializePyjsRuntime` returns the pyjs runtime (the emscripten `Module`) with
the API described in {doc}`JavaScript_API` (`exec`, `eval`, `exec_eval`,
`async_exec_eval`, `eval_file`, `to_js`, `FS`, ...), plus `installPackages`,
`unpackArchive` and `addFiles`.

Without a bundler, the package can be imported directly from a CDN, see [CDN](cdn.md).

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
  They are saved when there are new ones (checked every few seconds and when
  the page is hidden) or right away with `await pyjs.saveBytecode()`.
  Python checks each `.pyc` against the modification time + size of its
  source (kept from the archive), a stale one is compiled again.
  `bytecodeCache: false` turns it off.
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
| `archives` | `[]` | archives (`{url, path, sha256?}`) unpacked before Python starts, see below |
| `files` | `[]` | files (`{path, data}` or `{path, url}`) written before Python starts |
| `channels` | emscripten-forge 6x, conda-forge | channels the specs are solved against (also self-hosted ones, see below) |
| `cache` | `true` | package cache in Cache Storage (`false`, or a cache name) |
| `bytecodeCache` | `true` (with `cache`) | keep python's `.pyc` files of the packages for the next visit |
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
pyjs.exec("import sys; sys.path.insert(0, '/examples')");
```

## wasm32 or wasm64?

wasm32 is the default and works in all browsers. wasm64 (memory64) allows
more than 4 GB of memory (pyjs is linked with up to 16 GB) but needs a
browser with memory64 support. Extra packages are taken from the matching
channel subdir (`emscripten-wasm32` / `emscripten-wasm64`).

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
