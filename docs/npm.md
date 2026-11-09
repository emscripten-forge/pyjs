# npm package

The quickest way to use pyjs in a web application: the npm package contains
the pyjs runtime for **wasm32** and **wasm64** together with Python, its
standard library and the `pyjs` Python module. Extra conda packages
(numpy, pandas, ... from emscripten-forge) are solved and installed at runtime
with [mambajs](https://github.com/emscripten-forge/mambajs).
No conda environment, no `empack`, no server-side setup.

```{note}
The package is published as `@derthorsten/pyjs` for now; it will move to the
`@emscripten-forge` scope.
```

## Usage

```bash
npm install @derthorsten/pyjs
```

```js
import { initializePyjsRuntime } from "@derthorsten/pyjs";          // wasm32
// import { initializePyjsRuntime } from "@derthorsten/pyjs/wasm64"; // wasm64

const pyjs = await initializePyjsRuntime({ extraPackages: ["numpy"] });

pyjs.exec("import numpy as np");
pyjs.eval("int(np.arange(10).sum())");                 // 45
pyjs.exec_eval("x = 2\nx * 21");                       // 42
await pyjs.async_exec_eval("import asyncio\nawait asyncio.sleep(0)\n'done'");

await pyjs.installPackages(["regex"]);                 // install more later
await pyjs.installPackages(["scipy"], { verbose: true });  // with the mambajs log
```

`initializePyjsRuntime` returns the pyjs runtime (the emscripten `Module`) with
the API described in {doc}`JavaScript_API` (`exec`, `eval`, `exec_eval`,
`async_exec_eval`, `eval_file`, `to_js`, `FS`, ...), plus `installPackages`.

### From a CDN, without a bundler

```html
<script type="module">
  import { initializePyjsRuntime } from "https://cdn.jsdelivr.net/npm/@derthorsten/pyjs@4.1.0/dist/index.js";
  const pyjs = await initializePyjsRuntime();
  pyjs.exec("print('hello from python')");
</script>
```

Import `dist/index.js` (or `dist/wasm64.js`) directly, not the `/+esm`
variant of jsDelivr: the runtime and the Python environment are loaded
relative to the module (`import.meta.url`).

### In a web worker

The package works in the main thread and in module workers
(`new Worker(url, { type: "module" })`). In a worker the shared libraries of
packages are not preloaded (`dlopen` can compile synchronously there).

### With a bundler (Vite, webpack, Rollup, esbuild, Parcel)

`import { initializePyjsRuntime } from "@derthorsten/pyjs"` works in bundled
apps. The runtime wasm and the python environment (`assets/`) are not
JavaScript modules, so bundlers do not copy them; two ways to deploy them:

* **default:** if the assets are not found next to the module, they are
  loaded from jsDelivr, exactly the installed package version (one
  `console.warn`). Nothing to configure.
* **self-hosted** (offline, own CDN, no third-party requests): copy them into
  the static folder of your app (`public/` with Vite / Parcel, the folder
  copied to the output with webpack / Rollup / esbuild) and pass its url:

  ```bash
  npx @derthorsten/pyjs copy-assets public/pyjs              # both architectures
  npx @derthorsten/pyjs copy-assets public/pyjs --arch wasm32 # only one
  ```
  ```js
  const pyjs = await initializePyjsRuntime({ assetsUrl: "/pyjs/", cdnFallback: false });
  ```

  Re-run `copy-assets` after updating the package (the JS and the wasm must
  match).

## Options

| option | default | |
|---|---|---|
| `extraPackages` | `[]` | conda packages installed before Python starts |
| `channels` | emscripten-forge 6x, conda-forge | channels for extra packages |
| `assetsUrl` | `assets/` next to the module | url of a self-hosted copy of `assets/` (`copy-assets`) |
| `cdnUrl` | jsDelivr, this exact version | where `assets/` is loaded from when not next to the module |
| `cdnFallback` | `true` | `false`: error instead of loading from `cdnUrl` |
| `preloadSharedLibs` | main thread: `true`, worker: `false` | preload the `.so` files of packages |
| `print` / `printErr` | `console.log` / `console.warn` | stdout / stderr |
| `logger`, `verbose` | silent | progress messages |
| `moduleOptions` | | extra properties of the emscripten Module |

## wasm32 or wasm64?

wasm32 is the default and works in all browsers. wasm64 (memory64) allows
more than 4 GB of memory (pyjs is linked with up to 16 GB) but needs a
browser with memory64 support. Extra packages are taken from the matching
channel subdir (`emscripten-wasm32` / `emscripten-wasm64`).

## How it works

The package ships the runtime (`pyjs_runtime_browser.{mjs,wasm}`) and an
[empack](https://github.com/emscripten-forge/empack) packed environment with
Python and its standard library (without CPython's test suite and GUI
modules) plus the `pyjs` module. At startup they are extracted with untarjs
into the emscripten file system, then the interpreter is started
(`Module.init_phase_1` / `init_phase_2`, the same functions used by
xeus-python / jupyterlite-xeus). Python is pinned to the shipped build when
extra packages are solved.
