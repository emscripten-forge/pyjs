# @PACKAGE_NAME@

[pyjs](https://github.com/emscripten-forge/pyjs) for the browser: CPython
(emscripten-forge) with the python standard library and the pyjs python <-> JS
FFI, as one npm package. Extra conda packages (numpy, pandas, ... from
[emscripten-forge](https://github.com/emscripten-forge/recipes)) are solved and
installed at runtime.

Works in the main thread and in (module) web workers.

```js
import { initializePyjsRuntime } from "@PACKAGE_NAME@";          // wasm32
// import { initializePyjsRuntime } from "@PACKAGE_NAME@/wasm64"; // wasm64 (memory64)

const pyjs = await initializePyjsRuntime({ extraPackages: ["numpy"] });

pyjs.exec("import numpy as np");
console.log(pyjs.eval("int(np.arange(10).sum())"));          // 45
console.log(pyjs.exec_eval("x = 2\nx * 21"));                // 42
console.log(await pyjs.async_exec_eval(
  "import asyncio\nawait asyncio.sleep(0)\n'done'"));        // done

await pyjs.installPackages(["regex"]);                       // later installs
await pyjs.installPackages(["scipy"], { verbose: true });    // + mambajs log (or { logger })
```

Directly from a CDN, no bundler:

```html
<script type="module">
  import { initializePyjsRuntime } from "https://cdn.jsdelivr.net/npm/@PACKAGE_NAME@@@PACKAGE_VERSION@/dist/index.js";
  const pyjs = await initializePyjsRuntime();
  pyjs.exec("print('hello from python')");
</script>
```

Import `dist/index.js` (or `dist/wasm64.js`) directly, not jsDelivr's `/+esm`
variant: the runtime and the python environment are loaded relative to the
module (`import.meta.url`).

The returned object is the pyjs runtime (the emscripten `Module`): `exec`,
`eval`, `exec_eval`, `async_exec_eval`, `eval_file`, `to_js`, `FS`, ... ; see the
[pyjs docs](https://emscripten-forge.github.io/pyjs).

## Options of `initializePyjsRuntime`

| option | default | |
|---|---|---|
| `extraPackages` | `[]` | conda packages installed before python starts |
| `channels` | emscripten-forge 6x, conda-forge | channels for extra packages |
| `assetsUrl` | `assets/` next to the module | url of a self-hosted copy of `assets/` (`copy-assets`) |
| `cdnUrl` | jsDelivr, this exact version | where `assets/` is loaded from when not next to the module |
| `cdnFallback` | `true` | `false`: error instead of loading from `cdnUrl` |
| `preloadSharedLibs` | main thread: `true`, worker: `false` | preload `.so` files of packages |
| `print` / `printErr` | `console.log` / `console.warn` | stdout / stderr |
| `logger`, `verbose` | silent | progress messages |

## With a bundler (Vite, webpack, Rollup, esbuild, Parcel)

`import { initializePyjsRuntime } from "@PACKAGE_NAME@"` works in bundled
apps. The runtime wasm and the python environment (`assets/`) are not
JavaScript modules, so bundlers do not copy them; two ways to deploy them:

* **default:** if the assets are not found next to the module, they are
  loaded from jsDelivr, exactly the installed package version (one
  `console.warn`). Nothing to configure.
* **self-hosted** (offline, own CDN, no third-party requests): copy them into
  the static folder of your app (`public/` with Vite / Parcel, the folder
  copied to the output with webpack / Rollup / esbuild) and pass its url:

  ```bash
  npx @PACKAGE_NAME@ copy-assets public/pyjs              # both architectures
  npx @PACKAGE_NAME@ copy-assets public/pyjs --arch wasm32 # only one
  ```
  ```js
  const pyjs = await initializePyjsRuntime({ assetsUrl: "/pyjs/", cdnFallback: false });
  ```

  Re-run `copy-assets` after updating the package (the JS and the wasm must
  match).
