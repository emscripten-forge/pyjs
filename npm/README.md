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

const pyjs = await initializePyjsRuntime({ packages: ["numpy"] });

pyjs.runPython("import numpy as np");
console.log(pyjs.runPython("int(np.arange(10).sum())"));     // 45
console.log(pyjs.runPython("x = 2\nx * 21"));                // 42 (the last line's value)
console.log(await pyjs.runPythonAsync(
  "import asyncio\nawait asyncio.sleep(0)\n'done'"));        // done

const math = pyjs.pyimport("math");                          // a python module ...
console.log(math.sqrt(2));                                   // ... used from JS
math.destroy();                                              // release it

await pyjs.installPackages(["regex"]);                       // later installs
await pyjs.installPackages(["scipy"], { verbose: true });    // + solver log (or { logger })
```

Faster: pin the packages at build time, no solver in the browser:

```bash
npx @PACKAGE_NAME@ lock numpy pandas -o pyjs-lock.json
```
```js
const pyjs = await initializePyjsRuntime({
  urls: lock.wasm32,                              // [{url, sha256}] from pyjs-lock.json
  onProgress: ({ item, phase, done, total }) => console.log(item, phase, done, total),
});
```

Installed packages are cached in Cache Storage as their final layout, and
python's bytecode with them: a second visit only untars them, and imports do
not compile the sources again. Several workers: `compileRuntime()` once, pass
it as `wasmModule`.

Directly from a CDN, no bundler:

```html
<script type="module">
  import { initializePyjsRuntime } from "https://cdn.jsdelivr.net/npm/@PACKAGE_NAME@@@PACKAGE_VERSION@/dist/index.js";
  const pyjs = await initializePyjsRuntime();
  pyjs.runPython("print('hello from python')");
</script>
```

Import `dist/index.js` (or `dist/wasm64.js`) directly, not jsDelivr's `/+esm`
variant: the runtime and the python environment are loaded relative to the
module (`import.meta.url`).

The returned object is the pyjs runtime (the emscripten `Module`):
`runPython`, `runPythonAsync`, `pyimport`, `globals`, `FS`, ... The API
follows pyodide's and PEP 818; see the
[pyjs docs](https://emscripten-forge.github.io/pyjs).

## Options of `initializePyjsRuntime`

| option | default | |
|---|---|---|
| `packages` | `[]` | conda package specs, solved + installed before python starts |
| `urls` | `[]` | pinned conda packages (`{url, sha256?}` / URL strings), no solver |
| `archives` | `[]` | archives (`{url, path, cache?}`: tar / zip, gzip / bzip2 / zstd) unpacked before python starts; `cache: true` caches them like packages (immutable URLs only) |
| `files` | `[]` | files (`{path, data}` / `{path, url}`) written before python starts |
| `channels` | emscripten-forge 6x, conda-forge | channels the specs are solved against |
| `cache` | `true` | package cache in Cache Storage (`false`, or a cache name) |
| `bytecodeCache` | `true` (with `cache`) | keep python's `.pyc` files of the packages for the next visit (saved by `await pyjs.saveBytecode()`) |
| `verifySha256` | `false` | check sha256 values where given |
| `onProgress` | | `{item, phase, done, total}`: solve / download / cached / extract / link / start |
| `wasmModule` | | the runtime compiled already (`compileRuntime()`) |
| `assetsUrl` | `assets/` next to the module | url of a self-hosted copy of `assets/` (`copy-assets`) |
| `cdnUrl` | jsDelivr, this exact version | where `assets/` is loaded from when not next to the module |
| `cdnFallback` | `true` | `false`: error instead of loading from `cdnUrl` |
| `preloadSharedLibs` | main thread: `true`, worker: `false` | preload `.so` files of packages |
| `print` / `printErr` | `console.log` / `console.warn` | stdout / stderr |
| `logger`, `verbose` | silent | solver messages |

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

## License

pyjs: see `LICENSE`. The runtime and the python environment contain
third-party software (CPython, openssl, sqlite, zlib, emscripten's libc /
libc++, ...): their licenses are in `assets/<arch>/THIRD_PARTY_LICENSES.md`.
