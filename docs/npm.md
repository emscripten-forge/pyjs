# npm package

The quickest way to use pyjs in a web application: the npm package contains
the pyjs runtime for **wasm32** and **wasm64** together with Python, its
standard library and the `pyjs` Python module. Extra conda packages
(numpy, pandas, ... from emscripten-forge) are solved and installed at runtime
with [mambajs](https://github.com/emscripten-forge/mambajs).
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

const pyjs = await initializePyjsRuntime({ extraPackages: ["numpy"] });

pyjs.exec("import numpy as np");
pyjs.eval("int(np.arange(10).sum())");  // 45
pyjs.exec_eval("x = 2\nx * 21");        // 42
await pyjs.async_exec_eval(
  "import asyncio\nawait asyncio.sleep(0)\n'done'"
);

// install more later (verbose: with the mambajs log)
await pyjs.installPackages(["regex"]);
await pyjs.installPackages(["scipy"], { verbose: true });
```

`initializePyjsRuntime` returns the pyjs runtime (the emscripten `Module`) with
the API described in {doc}`JavaScript_API` (`exec`, `eval`, `exec_eval`,
`async_exec_eval`, `eval_file`, `to_js`, `FS`, ...), plus `installPackages`.

Without a bundler, the package can be imported directly from a CDN, see [CDN](cdn.md).

### In a web worker

The package works in the main thread and in module workers
(`new Worker(url, { type: "module" })`). In a worker the shared libraries of
packages are not preloaded (`dlopen` can compile synchronously there).

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
