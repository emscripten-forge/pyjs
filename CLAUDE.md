# pyjs

Python <-> JavaScript FFI for emscripten/wasm Python, built with pybind11 + embind.
C++ in `src/` + `include/pyjs/`, JS glue in `include/pyjs/pre_js/` + `post_js/`
(merged by `build_utils/merge_js.py`), Python module in `module/pyjs/`,
type stubs of the C++ module `pyjs_core` in `stubs/`.
Targets: Python 3.14, emscripten 6.0.8, emscripten-forge `6x` channel
(`https://repo.prefix.dev/emscripten-forge/6x`), `wasm32` and `wasm64`.
Packaged by the emscripten-forge recipe `recipes/recipes_wasm/pyjs` (packages
`pyjs` = python module, `libpyjs-static` = lib + runtime js/wasm, `pyjs-dev` = both).

## Build / test locally: always via pixi tasks (`pixi.toml`)

The CI runs the same tasks, so local == CI. Only pixi >= 0.84 is needed
(older ones do not know `emscripten-wasm64`; `pixi self-update`).

```bash
pixi run build wasm32                        # build pyjs (archs: wasm32 | wasm64 | "wasm32 wasm64")
pixi run test wasm32                         # npm package of the arch + browser tests (main + worker)
pixi run test wasm64 "chromium firefox webkit"
# test <arch> [browsers] [modes] [numpy|no-numpy] [jspi|no-jspi]
pixi run test wasm32 chromium "main worker" numpy no-jspi  # JSPI switched off at runtime
pixi run test wasm32 chromium main no-numpy
pixi run bench wasm32 [browsers] [modes] [filter]          # benchmarks
pixi run docs [out dir]                      # npm package + sphinx docs
pixi run npm-package [archs]                 # npm package (default wasm32 + wasm64)
pixi run test-npm [browsers]                 # npm package + both archs, lock CLI, bundlers
pixi run clean                               # rm -rf build_root (envs stay)
```

Task chain (tasks with args loop over `archs` via MiniJinja `| split`):
`envs` (`pixi install -e host-<arch> / npm-env-<arch> --platform
emscripten-<arch>`) -> `configure` (emcmake) -> `build` -> `pack` (empack
-> `build_root/npm/stage/<arch>/`) -> `npm-package` (+ `npm-ci`) ->
`test-page` -> `_run-tests` (`pyjs_test_driver run` loops browsers x modes
itself and prints the summary). `test-npm` = alias of `npm-package`,
`_run-tests` per arch, `test-lock`, `test-bundlers`.

Environments (`pixi.lock`, `.pixi/envs/`, gitignored):

| env | |
|---|---|
| `default` (feature `dev`) | native, **one for wasm32 + wasm64**: `emscripten-core`, cmake, empack, node, playwright (+ playwright-python), sphinx |
| `host-<wasm>` | emscripten env pyjs is built against (incl. `libarchive-static` for `src/extract.cpp`); nothing is installed into it |
| `npm-env-<wasm>` | the python env shipped in the npm package (python, pip, ca-certificates) |

Build output in `build_root/` (gitignored, never commit):

| dir | |
|---|---|
| `build_<wasm>` | cmake build dir |
| `npm/stage/<wasm>`, `npm/package`, `npm/tgz/*.tgz` | npm package |
| `pages/` | test pages (`pyjs_test_driver build-page`), `pages/bundler_projects/` the bundler apps |
| `benchmarks/<wasm>/` | benchmark json |
| `docs_html/` | built docs |

The tests / benchmarks mount `module/pyjs` from the source tree and take the
runtime (`pyjs_runtime_browser.{js,wasm}`) from the build dir, so Python-only
changes need no rebuild (the tasks still run cmake, which is a no-op).

WebGPU: `--use-port=emdawnwebgpu` is an `INTERFACE` link option of the `pyjs`
target (cmake option `PYJS_WEBGPU`, default ON; emscripten downloads the port
on first use), so every executable linking pyjs gets it: the runtime and, via
the exported `pyjsTargets.cmake`, xeus-python. As a `MAIN_MODULE` such an
executable carries the whole JS side of `webgpu.h` (`Module.WebGPU`, `wgpu*`)
for side modules. Tests: `tests/sync/test_webgpu.py` (in the runtime),
`tests/async/test_webgpu.py` (adapter / device; skips without `navigator.gpu` or
adapter, the usual case headless).

WebGL2 / SDL2: `MAIN_MODULE=1` implies `INCLUDE_FULL_LIBRARY`, so emscripten's
GL JS is always in the runtime, but only at WebGL1 level. cmake options
`PYJS_WEBGL` (`-lGL -sMAX_WEBGL_VERSION=2 -sFULL_ES3`) and `PYJS_SDL2`
(`-sUSE_SDL=2`, port downloaded on first use), both default ON, link them
**only into the runtime** (`PRIVATE` on `pyjs_runtime_browser`, not INTERFACE:
downstream executables like xeus-python are not forced to). Side modules
(imgui-bundle, ctypes / PyOpenGL via `ctypes.CDLL(None)`) resolve GL / SDL from
the main module. Python: `pyjs.set_canvas(canvas)` (`Module.canvas` +
`specialHTMLTargets["#canvas"]`, `pre_js/canvas.js`),
`pyjs.request_animation_frame_loop(cb)` (`emscripten_request_animation_frame_loop`,
`src/export_pyjs_module.cpp`). Tests: `tests/sync/test_webgl.py` (context via
ctypes; skips without WebGL2), `tests/async/test_animation_frame.py`.

Memory: the runtime is linked with `-sMAXIMUM_MEMORY` = 4GB (wasm32) / 16GB
(wasm64) (cmake cache var `PYJS_MAXIMUM_MEMORY`; emscripten's default is 2GB, also
for wasm64). `tests/sync/test_memory.py` allocates beyond 2 GiB / 4 GiB and
passes a pointer above that to JS (on wasm32 one object must be < 2 GiB:
`Py_ssize_t` is 32 bit, so it allocates chunks).

### Gotchas of the pixi setup
- Channels: workspace `6x, conda-forge` (emscripten builds of 6x win, strict
  priority); the `dev` feature prepends `conda-forge, 6x` (native tools
  from conda-forge, `emscripten-core` only exists in 6x; no osx-64 build of
  it, so the dev env is osx-arm64 + linux-64 only). A local recipe build
  (rattler-build output dir) goes first in the workspace channels.
- The emscripten envs cannot be installed by `pixi run` / setup-pixi
  ("unsupported-platform"): only `pixi install -e <env> --platform
  emscripten-<arch>` (task `envs`, nested pixi call: pixi must be on PATH).
- Task args are positional, in the order of `args`; several words in one arg
  (`"chromium firefox"`) are split by MiniJinja `| split` / argparse
  `nargs="+"`. Arg names: no dashes. Multi-line `cmd`s start with `set -e`
  (deno_task_shell does not stop on errors otherwise); backslash line
  continuations need TOML literal strings (`'''`).
- One dev env for both architectures: it has `emscripten-core`, not
  `emscripten_emscripten-wasm32` / `-wasm64` (those only depend on
  emscripten-core and, for wasm64, add `-m64` in their activation).
  `configure` / `build` add `-m64` to `EMCC_CFLAGS` (reaches every emcc call,
  e.g. the ports) for wasm64 only. The `CMAKE_ARGS` of the activation are not
  used, `configure` passes everything explicitly; the host libraries are
  linked from `CMAKE_INSTALL_PREFIX` (= the host env, never installed into).
  The emscripten library cache (in the dev env) keeps `wasm32-emscripten` /
  `wasm64-emscripten` apart.
- cmake + wasm64: `-m64` must be in `CMAKE_C_FLAGS` on the command line:
  `Emscripten.cmake` decides `CMAKE_SIZEOF_VOID_P` from `CMAKE_C_FLAGS`
  *before* `CFLAGS` from the environment are applied, so with `CFLAGS` only the
  first configure of a fresh build dir is 32 bit (a re-configure is 64 bit:
  hides the problem). pyjs' CMakeLists adds `-m64` itself (`WASM64`).
- The wasm64 packages of the channel (xeus-lite, zlib, ...) have that
  problem: 64 bit binaries, but their `*ConfigVersion.cmake` say 32 bit (and
  reject 64 bit projects). Not used by pyjs anymore (the docs do not build
  xeus-python), matters for projects building against them. Never edit env
  files in place: they are hardlinked to the package cache.
- `CMakeLists.txt` runs `$ENV{CONDA_PREFIX}/bin/python` (merge_js.py), so
  `CONDA_PREFIX` must be the dev env (it is, in every task).
- empack finds its default config via `sys.prefix.startswith(CONDA_PREFIX)`.
- A build dir configured with another toolchain path (e.g. an old env) gets
  its cmake cache reset on the next configure ("You have changed variables
  that require your cache to be deleted"): harmless, it reconfigures.

## Tests

- One suite (`tests/`), run inside the browser by `tests/main.py`
  (`async def main(options) -> dict`): `tests/js/test_*.js` (ES modules,
  exported `test_*(pyjs)`), `tests/async/test_*.py` (own runner, loaded by
  path: `async` is a keyword), `tests/sync/test_*.py` (pytest). Helpers:
  `tests/helpers.py`. The download tests fetch `/test-data/all_bytes.bin`,
  generated by the driver (no binaries in the repo; absolute path: works on
  every page / worker).
- pytest cannot run async tests in the browser: `pytest.main()` is synchronous and
  the browser event loop cannot be blocked (`WebLoop.run_until_complete` just
  schedules). Async tests therefore go into `tests/async/`.
- `pyjs_test_driver/` (python, replaces pyjs-code-runner):
  `build-page <kind> --out <dir>` *creates* a page dir (`pages.py`),
  `run <dir> --browser --mode main|worker [--disable-jspi] [--entry
  benchmarks]` *runs* one (`driver.py`: stdlib http server serving the page
  dir at `/` + `tests/` / `benchmarks/` with a generated `__files__.json`,
  playwright). Page contract: `index.html` reads options from the url, gets
  pyjs from `page.js` (`createPyjs(options)`), calls
  `harness.runSuite(createPyjs, options)` (writes the suite into `Module.FS`,
  sets `globalThis.pyjs`, awaits `main(options)`), sets
  `window.__pyjs_result`; worker mode: `worker.js`, console + result relayed
  via postMessage.
- Only npm-based pages (pyjs 5: the vanilla page is gone; `test <arch>`
  builds the npm package of that arch). Page kinds: `npm` (the package,
  `TEST_PACKAGES` via `packages` (solved), a test-channel package via `urls`
  (pinned), `archives`, `files`, `onProgress` recorded in
  `globalThis.__pyjs_progress`; network), `vite` / `webpack`
  / `rollup` / `esbuild` / `parcel` (bundled app around
  `web/bundler_main.js`, runtime files via `copy-assets` + `cdnUrl`, main
  thread only, built with `CI=true`).
- The npm package loads the runtime as ES module = strict mode: an undeclared
  variable in pre_js / post_js is a ReferenceError there (silently a global
  in the classic script). Check: `tsc --allowJs --checkJs --noEmit` on
  `include/pyjs/{pre,post}_js/*.js` (TS2304 besides the emscripten globals).
- Tests must pass in the main thread *and* in a worker, and in chromium,
  firefox and webkit.
- npm / bundler pages need the network (mambajs fetches from prefix.dev,
  which sometimes answers without CORS headers): `run --retries 5` (10 s
  apart, `--retry-delay`) reruns a
  page whose *setup* failed (`{ok: false, error}`, no test ran), never failed
  tests. Vanilla pages are offline, no retries.
- No assertions that depend on timing (CI runners are slow and noisy): make the
  order explicit (e.g. a JS promise the test resolves itself), check structure
  instead of speed (`_CountSetTimeout` in `tests/async/test_webloop.py`: the
  fast path uses no `setTimeout`), only lower bounds for delays ("at least"),
  and timeouts only as hang guards. Speed belongs in `benchmarks/`.

## How JS and Python call each other

JS -> Python (every entry goes through embind into wasm):
- the embind class `pyobject` (= `py::object`, `src/export_py_object.cpp`):
  `_raw_apply`, `_raw_getitem`, `_raw_getattr`, `__call__`, `__usafe_void_void__`,
  `__usafe_void_val__`, `__toPrimitive`, `toString`, `toJSON`. JS helpers on its
  prototype (`include/pyjs/pre_js/init.js`): `py_call` / `py_apply` (-> `_raw_apply`),
  `get` (-> `_raw_getitem`), `_getattr`; they turn `{has_err, ...}` results into throws.
- free embind functions (`src/export_js_module.cpp`): `_exec`, `_eval`, `_eval_file`,
  `_initialize_interpreter`, ...; wrapped as `Module.exec` / `eval` / `eval_file`
  (`init.js`). `Module.exec_eval` / `async_exec_eval` call `pyjs.exec_eval` /
  `pyjs.async_exec_eval` via `pyobject.py_call`.
- Python callables handed to JS: `create_callable` (`module/pyjs/core.py`) ->
  bound `pyobject.py_call`; `create_once_callable` -> `Module._create_once_callable`
  (`pre_js/create_once_callable.js`). The webloop: `call_soon` -> MessageChannel
  `onmessage` -> `create_callable(_MacrotaskQueue._run_next)`; `call_later` ->
  `setTimeout` + `_create_once_callable_unsave_void_void` (-> `__usafe_void_void__`).
  So every asyncio task step is a *sync* JS -> Python call from a JS event.
- The test harness (`pyjs_test_driver/web/harness.js`) awaits
  `pyjs.async_exec_eval("... await main(options)")`: Python is re-entered from
  JS events while the asyncio tasks run.

Python -> JS: `pyjs_core.internal.*` (`src/export_js_proxy.cpp`) call JS helpers on
`Module` (`_apply_try_catch`, `_getattr_try_catch`, ... in `pre_js/apply.js`,
`get_set_attr.js`). They never throw, they return `{has_err, err, has_ret, ret,
type_string}` (`pre_js/wrap_result.js`); C++ `wrap_result` converts the value or raises
via `pyjs.error_to_py_and_raise` (`module/pyjs/convert.py`) -> `JsException` subclasses
(`module/pyjs/error_handling.py`). The `js` module / `pyodide.ffi` polyfill:
`module/pyjs/core.py`, `module/pyjs/pyodide_polyfill.py`.

Awaiting a rejected JS promise raises a `JsException` subclass (`error_to_py`,
like synchronous JS errors; pyodide compatible: `.name` / `.message`, e.g.
`AbortError`), which is also a `RuntimeError` (it used to be a plain
`RuntimeError` with a JSON string). `module/pyjs/extend_js_val.py`,
`include/pyjs/pre_js/promise.js`.

## asyncio event loop (`module/pyjs/webloop.py`)

- `WebLoop.call_soon` runs callbacks via the private `_MacrotaskQueue`:
  a private `MessageChannel` (node: `setImmediate`). `setTimeout(cb, 0)` is
  clamped to >= 4ms when nested, which made `asyncio.sleep(0)` take ~4.7ms
  (now ~5us). `call_later(delay > 0)` uses `setTimeout`.
- Safari is excluded (MessageChannel issues, pyodide#4583) and keeps the
  `setTimeout` fallback; there `call_soon` vs an earlier `call_later` ordering
  is not guaranteed.
- The mechanism must stay invisible to the outside: nothing exported, nothing
  on `globalThis` / `Module` (there is a test for this). Consumers like
  xeus-python must not need extra files.
- `webloop.py` is adapted from pyodide (webloop.py + `src/js/scheduler.ts`):
  keep the MPL-2.0 header, `webloop_LICENSE`, `webloop_README.md`.
- Tests: `tests/async/test_webloop.py`.

## JSPI (`pyjs.run_sync` / `can_run_sync`)

- **One build for all browsers**: no `-sJSPI`. JSPI is used when the browser
  has `WebAssembly.Suspending` / `WebAssembly.promising` (`pyjs.jspi_enabled()`),
  otherwise pyjs behaves as without it (`can_run_sync()` False, `run_sync`
  raises, urllib3 falls back to XHR). Same pattern as pyodide.
- Suspend point: `EM_JS pyjs_jspi_await` (`src/export_js_proxy.cpp`), its JS
  replaces the import with `new WebAssembly.Suspending(...)` before
  instantiation if supported. Entry point: the plain wasm export
  `pyjs_raw_apply_promising` (`src/export_py_object.cpp`), wrapped with
  `WebAssembly.promising` at runtime; JS side `py_apply_promising`
  (`include/pyjs/pre_js/jspi.js`). The webloop enters task steps through it, so
  `run_sync` works in asyncio tasks, also in xeus-python cells (they run as
  coroutines).
- Suspending only works with **no JS frame** between the promising entry and the
  suspend point. Only one suspended Python stack at a time (keeps the C stack /
  CPython thread state LIFO); `can_run_sync()` is False in sync JS callbacks,
  while another `run_sync` waits, and for promising calls nested in running
  wasm (`depth`). `run_sync` leaves / re-enters the current asyncio task.
- Tests: `pixi run test <wasm> <browsers> "main worker" numpy no-jspi` switches JSPI off at
  runtime (`run --disable-jspi` -> option `disable_jspi` ->
  `pyjs.core._disable_jspi()` in `tests/main.py`), CI runs both. A browser without the APIs at all can be
  simulated with playwright: `delete WebAssembly.Suspending` in an init script.
  `tests/async/test_jspi.py` (async: run_sync needs a task step).
  A failed suspension can hang a test run: use a timeout.
- CPython calls C functions through `_PyEM_TrampolineCall`: must be the wasm-gc
  trampoline, the JS fallback is a JS frame ("trying to suspend JS frames").
  Needs libpython from the emscripten-forge python recipe with the trampoline
  patches (0016 / 0017 + wasm64 `emscripten_trampoline_inner_wasm64.c`,
  build >= 6).
- Test a local recipe build: put `<recipes>/output` first in the workspace
  `channels` of `pixi.toml` (re-solves `pixi.lock`; do not commit that);
  rattler-build may leave a stale `repodata.json` when it overwrites a
  package with the same file name, and the installer then rejects the "wrong
  size" package.
- With JSPI, urllib3 uses its `fetch` path (`pyodide.ffi.run_sync` polyfill);
  it slices `Uint8Array.to_py()` results, so `TypedArrayBuffer` supports
  memoryview-style indexing (`module/pyjs/convert.py`).

## npm package (`npm/`, `pixi run npm-package`)

- One package with both builds: `.` (= wasm32), `./wasm32`, `./wasm64`; name via
  `NPM_PACKAGE_NAME` (now `@derthorsten/pyjs`, later `@emscripten-forge/pyjs`),
  version = `project(pyjs VERSION ...)` in CMakeLists.txt (both read by
  build.mjs itself, `--name` / `--version` override). TypeScript in
  `npm/src/` (`runtime.ts` = the init), assembled by `npm/build.mjs` (esbuild:
  self-contained ESM, all files incl. chunks in `dist/`; the solver mambajs +
  rattler, ~6 MB, is a lazy chunk). The published `package.json` is written by
  build.mjs (`npm/package.json` is only the build tooling).
- `pixi run npm-package [archs]`: per arch: normal pyjs build, the env
  `npm-env-<arch>` packed by empack (task `pack`) with
  `npm/empack_config.yaml` (drops CPython's `test/` = 75% of the python
  package), + `module/pyjs` as mount, `build_utils/npm_env_meta.py` adds
  channels + a pinned python spec (mambajs needs `channels`; the pin keeps
  the solver from replacing the running python) -> `build_root/npm/stage/<wasm>/`;
  then `build_root/npm/package/` + `npm pack` -> `build_root/npm/tgz/*.tgz`.
  `pixi run test-npm` tests it fully (bundlers: `pixi run test-bundlers` alone).
- pyjs 5 init: the core (libpyjs + pre/post js) never fills the file system
  or preloads shared libs; whoever fills it calls `Module.startPython()` (synchronous)
  (`pre_js/init.js`: python version from C++ `_python_version`, error without
  `/lib/pythonX.Y`, idempotent). The classic API (`bootstrap_from_empack_*`,
  `init_phase_*`, `_untar`, `_install_conda_file`, untar/inflate C++,
  `load_pkg.js`, `dynload.js`, `fetch.js`) is gone. The runtime target
  (not libpyjs) has `src/extract.cpp`: `Module._extract_archive(bytes, dest,
  {conda, meta, rename})` on libarchive (tar / zip, gzip / bzip2 / zstd, no
  xz; .conda = zip of pkg-/info-*.tar.zst), own write loop (no `..` /
  absolute paths / writes through the archive's symlinks; hard links ->
  copies), returns `{files, sharedLibs, meta}`. Tests: `tests/sync/test_extract.py`.
- npm init (`runtime.ts`), all in parallel: `createModule` (or `wasmModule`
  via `instantiateWasm`), solve (`solve.ts`: mambajs, lazy chunk, also
  `empackLockToMambajsLock` / `formatChannels` / `computePackageUrl` from it:
  the main bundle has no mambajs / untarjs), downloads (`fetch.ts`: byte
  progress, sha256 only with `verifySha256`, max 6 parallel); package cache
  (Cache Storage `pyjs-packages-v2`, by package URL): the installed layout
  as uncompressed tar (`_extract_archive` option `tar`) + relocation
  placeholders in a header, a warm install only untars (bypassed with
  `verifySha256` + sha256); bytecode cache (`bytecode.ts`,
  `pyjs-packages-v2-bytecode`, by package / env tarball URL): the `.pyc`
  files of each package's `.py` files (`Module._tar_files`), restored with
  the package, saved when `__pycache__` entry counts grow (3 s interval,
  page hidden, `Module.saveBytecode()`). Valid because the extraction keeps
  the archive mtimes (`set_mtime`) and `relocate` restores them (python
  checks a `.pyc` against source mtime + size); then extraction in order
  env tarballs -> packages (`install.ts`: conda layout, `site-packages/` ->
  `lib/pythonX.Y/site-packages/`, `info/paths.json` text placeholders -> "",
  per-package file lists, old files removed before a replacement) ->
  `archives` -> `files` -> `startPython` -> `sharedlibs.ts` (dlopen promise,
  libs RTLD_GLOBAL first, `.cpython-*.so` / lib-dynload RTLD_LOCAL; main
  thread only; *after* python started: extension modules' static
  initializers use the C API, e.g. matplotlib's ft2font crashes otherwise).
  `Module.initTimings`: phase times (ms) of the init, `Module.installTimings`
  of the last `installPackages` (`state.timings` points to the running one). Options: `packages` (specs), `urls` (pinned
  `{url, sha256?}`), `archives`, `files`, `cache`, `verifySha256`,
  `onProgress`, `wasmModule`, `env`. `python` / `pyjs` are never replaced.
- Returns the Module + `installPackages(specs | pinned)`, `unpackArchive`,
  `addFiles` (serialized in a queue). Entries also export `compileRuntime()`.
  CLI: `npx <pkg> lock <specs>` (`src/lock.ts`, bundled for node into
  `bin/lock.mjs`) -> `{wasm32: [{url, sha256}], ...}`; the docs build pins the
  playground's numpy with it (`pyjs-lock.json`).
- Tests: the full test suite on npm pages (both archs x main / worker) and on
  the 5 bundler pages (see Tests). npm-only tests: `tests/npm/test_*.py`
  (async), run by `tests/main.py` only with option `npm_package` (the harness
  sets it when the Module has `installPackages`); `test_install.py`: pinned at
  init / runtime, `.conda`, relocation, replacing, sha256, cache, bytecode
  cache, progress, `compileRuntime`.
  `tests/npm/test_channel.py` installs from a self-hosted channel (static
  files, like GitHub Pages next to docs) that the driver generates at
  `/test-channel/` (`pyjs_test_driver/test_channel.py`: noarch python package
  + arch package, rattler-build output layout; unindexed for pinned tests: a
  `.conda` package, arch package v2.0.0). The rattler gateway first
  probes `repodata_shards.msgpack.zst` / `repodata.json.zst` / `.bz2` (404s
  are fine), then reads `repodata.json`.
- Channel order = priority. mambajs' `install` appends new channels *after*
  the lock's (the shipped env: emscripten-forge, conda-forge), so `solve` in
  `solve.ts` puts the requested channels first (`formatChannels` from
  mambajs-core): a self-hosted CI build must win over a published package
  (`test_self_hosted_channel_has_priority`: a fake `tabulate` 0.0.1 beats
  conda-forge's 0.9.x).
- Archives: option `archives: [{url, path}]` (unpacked by `_extract_archive`
  before python starts) / `Module.unpackArchive({url, path})` (later, then
  `importlib.invalidate_caches()`); paths resolved against `path` (never the
  cwd), directory entries not listed, paths outside `path` rejected.
  Tests: `tests/npm/test_archives.py` with archives the driver generates
  (`pyjs_test_driver/test_archives.py`); the npm / bundler pages pass one in
  `archives`.
- CI: `.github/workflows/npm.yml` builds + tests (all browsers), publishes on
  release tags (`4.1.0`, must equal the package version) / manual dispatch;
  npm trusted publishing (OIDC, configured on npmjs.com for this repo +
  `npm.yml`, no token), variable `NPM_PACKAGE_NAME`. Manual publish:
  `cd build_root/npm/package && npm publish --access public`.
- On jsDelivr import `dist/index.js` directly, not `/+esm` (re-bundling
  breaks the `import.meta.url` asset paths).
- Assets (`assets/<arch>/`: runtime + packed env) are
  fetched at runtime, bundlers do not copy them. Lookup (`resolveAssets` in
  `runtime.ts`): `assetsUrl` -> `assets/` next to the module (probe of
  `<arch>/empack_env_meta.json`, must parse as env meta: dev servers answer
  unknown paths with index.html) -> `cdnUrl` (default jsDelivr, exact
  version, baked in via esbuild `define`) unless `cdnFallback: false`.
  Self-hosting: `npx <pkg> copy-assets <dir>` (`npm/bin/pyjs.mjs`).
  Bundler pitfalls handled in `build.mjs`: no `new URL("<dir literal>",
  import.meta.url)` (Parcel fails on directories), the runtime `import(url)`
  lives in the unminified `dist/load-runtime.js` (esbuild's minifier drops
  the `webpackIgnore` / `@vite-ignore` comments), `__filename` /
  `__dirname` defined as `undefined` (webpack rewrites `typeof __filename`
  in the untarjs glue bundled by mambajs-core, lazy solver chunk).
- `pixi run test-bundlers` (part of `test-npm`): pages built with vite,
  webpack, rollup, esbuild, parcel around the packed package
  (`build_root/npm/tgz/`), projects in `build_root/pages/bundler_projects/`.

## Benchmarks (`benchmarks/`)

pytest-benchmark cannot await in the browser, so `benchmarks/harness.py` is a
small async-aware replacement (`benchmark(fn, *args)`,
`await benchmark.aio(coro_fn, *args)`, `ops=` for loops inside JS).
`benchmarks/main.py` discovers `bench_*` functions in `bench_*.py` and prints a
`PYJS_BENCH_RESULT_JSON:` line which the driver extracts (files written in
the browser FS do not reach the host). Compare runs via the stored json files;
pure-JS benchmarks (`raw_js_*`) show the run-to-run noise.

## Docs (`docs/`, Sphinx)

- Sphinx + myst-parser (markdown pages) + pydata-sphinx-theme + sphinx-autoapi
  (parses `module/` and `stubs/` statically: `pyjs_core` / `js` only exist in
  the browser). Docstrings are markdown flavoured, converted in `docs/conf.py`
  (fences / inline code) + napoleon (google sections).
- Pages: quickstart (index), npm, CDN, C++ / static library (advanced),
  playground, JavaScript API, Python API (autoapi), design, development.
  No JupyterLite / xeus-python in the docs anymore (only links).
- `@PYJS_NPM_PACKAGE@` / `@PYJS_NPM_VERSION@` in pages are filled in by
  `docs/conf.py` (version from CMakeLists.txt).
- Playground: `docs/_extra/playground/index.html` (monokai, Monaco from
  cdnjs, `workerMain.js` without `.min`), loads the npm package built by
  `pixi run docs` and deployed as `<html root>/pyjs/`. Python helpers
  injected by the page: `install(specs, verbose)`, `stopped()`,
  `on(event, handler)` (canvas listeners, removed on run / example switch).

## CI

- All workflows: `concurrency` per workflow + PR number / ref with
  `cancel-in-progress`: a new push / PR update cancels the older run (each
  release tag is its own group).
- All use `prefix-dev/setup-pixi` (pixi version pinned, `pixi.lock`, default
  env cached; the emscripten envs come from the task `envs`) and
  `pixi run playwright install --with-deps <browsers>` first.
- `.github/workflows/main.yml`: matrix wasm32/wasm64 x chromium/firefox/webkit,
  `pixi run test <wasm> <browser>`, again with JSPI off, plus a no-numpy
  run (main thread). Jobs have a timeout (a failed suspension hangs).
- `.github/workflows/npm.yml`: `pixi run test-npm`, uploads
  `build_root/npm/tgz/*.tgz`, publishes it on release tags.
- `.github/workflows/bench.yml`: `pixi run bench <wasm> <browser>` for wasm32 /
  wasm64 x chromium / firefox / webkit (main thread + worker), manual only
  (workflow_dispatch); `benchmarks/report.py` writes the results as
  markdown tables to the job summary, the json files are artifacts.
- `.github/workflows/docs.yml`: `pixi run docs docs_build/html`,
  deploys `docs_build/html` to GitHub Pages from `main`.




## Shell commands (for Claude)

This environment blocks reads outside the working directory and asks for
permission on any Bash command it cannot statically analyze. Therefore:

- Use literal absolute paths in Bash commands. Do not use shell variables
  (`S=...; cd $S`), `for` loops, or `$(...)` to build paths.
- Do not `cd` into computed directories; one command per target.
- Temporary files (e.g. cloned pyjs sources for API diffs) go in the session
  scratchpad, addressed by literal absolute path.
- Change files only with the Edit / Write tools. Never `sed -i`, `awk`, `perl -i`
  or heredoc redirects to modify files (they cannot be checked, show no diff,
  and BSD sed on macOS silently ignores GNU syntax like `\b`).
- No process substitution `<(...)`, `$(...)`, or `;`/`&&` chains of several
  commands: one plain command per call.
- Don't read outside the repo (`~`, `which`, other envs) to discover the setup;
  ask the user instead.
- Subagents do not reliably follow these rules on their own: every subagent
  prompt repeats them (one plain command per call, literal absolute paths, no
  pipes, no redirects like `2>/dev/null`, no `&&` / `;`, no `$(...)`, no `cd`;
  the Read tool for file contents).
