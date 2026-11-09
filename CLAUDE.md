# pyjs

Python <-> JavaScript FFI for emscripten/wasm Python, built with pybind11 + embind.
C++ in `src/` + `include/pyjs/`, JS glue in `include/pyjs/pre_js/` + `post_js/`
(merged by `build_utils/merge_js.py`), Python module in `module/pyjs/`,
type stubs of the C++ module `pyjs_core` in `stubs/`.
Targets: Python 3.14, emscripten 6.0.8, emscripten-forge `6x` channel
(`https://repo.prefix.dev/emscripten-forge/6x`), `wasm32` and `wasm64`.
Packaged by the emscripten-forge recipe `recipes/recipes_wasm/pyjs` (packages
`pyjs` = python module, `libpyjs-static` = lib + runtime js/wasm, `pyjs-dev` = both).

## Build / test locally: always via `build_local.sh`

The CI uses the same script, so local == CI. Only micromamba is needed.

```bash
./build_local.sh build wasm32                # build + install pyjs
./build_local.sh test wasm32                 # + browser tests (main thread + worker)
BROWSERS="chromium firefox webkit" ./build_local.sh test wasm64
DISABLE_JSPI=1 ./build_local.sh test wasm32  # JSPI switched off at runtime
TEST_ENV=no-numpy ./build_local.sh test wasm32
./build_local.sh bench wasm32                # benchmarks
BENCH_FILTER=async ./build_local.sh bench wasm32
./build_local.sh docs [--test]               # sphinx docs + jupyterlite (wasm32 + wasm64)
./build_local.sh npm [--test]                # npm package (wasm32 + wasm64)
./build_local.sh test wasm32 --fresh         # recreate envs / build dirs first
```

Useful env vars (full list at the top of the script): `ARCHS` (archs of
docs / npm, default both), `BROWSERS` (chromium firefox webkit; webkit = Safari engine),
`BACKENDS` (browser-main browser-worker), `BENCH_FILTER`, `BUILD_ENV_PREFIX`
(use an existing dev env, never deleted; CI), `TEST_ENV` (`default` |
`no-numpy`: packages of the test env), `PYJS_CODE_RUNNER_DIR` (local
pyjs-code-runner checkout, pip -e installed into the dev env),
`PLAYWRIGHT_INSTALL_ARGS` (`--with-deps` on CI), `DOCS_OUT_DIR`, `DISABLE_JSPI=1`,
`EXTRA_CHANNELS` (channels searched first when creating envs).

Everything lives in `build_root/` (gitignored, never commit):

| dir | env file | |
|---|---|---|
| `dev_prefix` | `environment-dev.yml` | native, **one for wasm32 + wasm64**: `emscripten-core`, cmake, node, pyjs-code-runner, sphinx, jupyterlite, empack, ... |
| `host_prefix_<wasm>` | `environment-host.yml` | emscripten env pyjs is built against + installed into, also the xeus-python deps for `docs` (build-only, so one big env) |
| `deploy_prefix_<wasm>` | none: `DEPLOY_SPECS` in build_local.sh | env the tests / benchmarks run in (`deploy_no_numpy_prefix_<wasm>` for `TEST_ENV=no-numpy`) |
| `npm_env_prefix_<wasm>` | none: `NPM_ENV_SPECS` | `npm`: the env shipped in the package (python only) |
| `build_<wasm>`, `build_xeus_python_<wasm>` | | cmake build dirs |
| `benchmarks/<wasm>/` | | benchmark logs + json |
| `docs_html/` | | built docs |

The tests / benchmarks mount `module/pyjs` from the source tree and take the
runtime (`pyjs_runtime_browser.{js,wasm}`) from the build dir, so Python-only
changes need no rebuild (the script still runs cmake/make, which is a no-op).

Memory: the runtime is linked with `-sMAXIMUM_MEMORY` = 4GB (wasm32) / 16GB
(wasm64) (cmake cache var `PYJS_MAXIMUM_MEMORY`; emscripten's default is 2GB, also
for wasm64). `tests/tests/test_memory.py` allocates beyond 2 GiB / 4 GiB and
passes a pointer above that to JS (on wasm32 one object must be < 2 GiB:
`Py_ssize_t` is 32 bit, so it allocates chunks).

### Gotchas in build_local.sh
- Structure: the dev env is activated once, `use_arch <wasm>` sets
  everything per architecture (`PREFIX` = host env, build dir, `CMAKE_ARGS`,
  compiler flags); `docs` / `npm` loop over `ARCHS` in one process.
- One dev env for both architectures: it has `emscripten-core`, not
  `emscripten_emscripten-wasm32` / `-wasm64` (those only depend on
  emscripten-core and, for wasm64, add `-m64` to `EMCC_CFLAGS` / `CFLAGS` /
  `CXXFLAGS` / `LDFLAGS` in their activation). `use_arch` does that itself
  (`EMCC_CFLAGS` reaches every emcc call, e.g. xeus-python). It does not use
  the `CMAKE_ARGS` of the activation (they bake in `PREFIX` at activation
  time) but sets its own. The emscripten library cache keeps
  `wasm32-emscripten` / `wasm64-emscripten` apart.
- cmake + wasm64: `-m64` must be in `CMAKE_C_FLAGS` on the command line:
  `Emscripten.cmake` decides `CMAKE_SIZEOF_VOID_P` from `CMAKE_C_FLAGS`
  *before* `CFLAGS` from the environment are applied, so with `CFLAGS` only the
  first configure of a fresh build dir is 32 bit (a re-configure is 64 bit:
  hides the problem). pyjs' CMakeLists adds `-m64` itself (`WASM64`).
- The wasm64 packages of the channel (xeus, xeus-lite, zlib, ...) have that
  problem: 64 bit binaries, but `*ConfigVersion.cmake` say 32 bit and reject
  64 bit projects. `fix_wasm64_cmake_configs` disables the check in the host
  env with `sed -i` (new file: micromamba hardlinks env files to its package
  cache, editing in place would change the cache and every later env).
- Activation scripts are not `set -u` safe (wrapped in `set +u`).
- `CMakeLists.txt` runs `$ENV{CONDA_PREFIX}/bin/python` (merge_js.py), so
  `CONDA_PREFIX` must be the build env.
- empack finds its default config via `sys.prefix.startswith(CONDA_PREFIX)` (plain
  string prefix): a stale `CONDA_PREFIX=.../build_prefix` breaks envs named
  `.../build_prefix_wasm32`. Run things with the right env activated.
- Do not edit `build_local.sh` while it runs (bash reads scripts lazily, you get
  bogus syntax errors).

## Tests

- `tests/main.py` (async main via `pyjs_code_runner ... --async-main`) first runs
  the `async def test_*` functions from `tests/atests/` (own minimal runner),
  then the sync pytest tests in `tests/tests/`.
- pytest cannot run async tests in the browser: `pytest.main()` is synchronous and
  the browser event loop cannot be blocked (`WebLoop.run_until_complete` just
  schedules). Async tests therefore go into `tests/atests/` (exported via
  `tests/atests/__init__.py`).
- Tests must pass in the main thread *and* in a worker, and in chromium,
  firefox and webkit.
- No assertions that depend on timing (CI runners are slow and noisy): make the
  order explicit (e.g. a JS promise the test resolves itself), check structure
  instead of speed (`_CountSetTimeout` in `tests/atests/webloop_tests.py`: the
  fast path uses no `setTimeout`), only lower bounds for delays ("at least"),
  and timeouts only as hang guards. Speed belongs in `benchmarks/`.
- pyjs-code-runner >= 3.3.0 has `--browser chromium|firefox|webkit`
  (repo: emscripten-forge/pyjs-code-runner, CI installs it from the git tag).

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
- pyjs-code-runner `--async-main` (`pyjs_code_runner/js/utils.js`):
  `pyjs.exec(... asyncio.ensure_future(main_runner()))`, then polls
  `pyjs.eval("_async_done_[0]")` from JS: Python is re-entered while tasks run.

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
- Tests: `tests/atests/webloop_tests.py`.

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
- Tests: `DISABLE_JSPI=1 ./build_local.sh test <wasm>` switches JSPI off at
  runtime (`/test_config/config.json` -> `pyjs.core._disable_jspi()` in
  `tests/main.py`), CI runs both. A browser without the APIs at all can be
  simulated with playwright: `delete WebAssembly.Suspending` in an init script.
  `tests/atests/jspi_tests.py` (async: run_sync needs a task step).
  A failed suspension can hang a test run: use a timeout.
- CPython calls C functions through `_PyEM_TrampolineCall`: must be the wasm-gc
  trampoline, the JS fallback is a JS frame ("trying to suspend JS frames").
  Needs libpython from the emscripten-forge python recipe with the trampoline
  patches (0016 / 0017 + wasm64 `emscripten_trampoline_inner_wasm64.c`,
  build >= 6).
- Test a local recipe build: `EXTRA_CHANNELS=<recipes>/output ./build_local.sh ...`
  with a fresh host env (`rm -rf build_root/host_prefix_<wasm>`); rattler-build
  may leave a stale `repodata.json` when it overwrites a package with the same
  file name, and micromamba then rejects the "wrong size" package.
- With JSPI, urllib3 uses its `fetch` path (`pyodide.ffi.run_sync` polyfill);
  it slices `Uint8Array.to_py()` results, so `TypedArrayBuffer` supports
  memoryview-style indexing (`module/pyjs/convert.py`).

## npm package (`npm/`, `build_local.sh npm`)

- One package with both builds: `.` (= wasm32), `./wasm32`, `./wasm64`; name via
  `NPM_PACKAGE_NAME` (now `@derthorsten/pyjs`, later `@emscripten-forge/pyjs`),
  version = `project(pyjs VERSION ...)` in CMakeLists.txt. TypeScript in
  `npm/src/` (`runtime.ts` = the init), assembled by `npm/build.mjs` (esbuild:
  self-contained ESM, all files incl. chunks in `dist/`; the solver mambajs +
  rattler, ~6 MB, is a lazy chunk). The published `package.json` is written by
  build.mjs (`npm/package.json` is only the build tooling).
- `./build_local.sh npm [--test]`: per arch (`ARCHS`): normal pyjs build, env from
  `NPM_ENV_SPECS` (python only) packed by empack with
  `npm/empack_config.yaml` (drops CPython's `test/` = 75% of the python
  package), + `module/pyjs` as mount, `build_utils/npm_env_meta.py` adds
  channels + a pinned python spec (mambajs needs `channels`; the pin keeps
  the solver from replacing the running python) -> `build_root/npm/stage/<wasm>/`;
  then `build_root/npm/package/` + `npm pack` -> `build_root/npm/*.tgz`.
  `ARCHS=wasm32` (local only), `NPM_TEST_NETWORK=0`, `NPM_MINIFY=0`.
- Init (`runtime.ts`) = the jupyterlite-xeus path via mambajs-core:
  `createModule` (`assets/<arch>/pyjs_runtime_browser.mjs` = the classic
  MODULARIZE js + `export default createModule`, located via
  `import.meta.url`) -> `bootstrapEmpackPackedEnvironment` (untarjs into
  `Module.FS` *before* python starts) -> extra packages (mambajs `install`,
  lock platform `emscripten-<arch>`) -> `bootstrapPython` (=
  `init_phase_1/2`) -> `loadSharedLibs` (main thread only). untarjs is
  created by us with its wasm at `dist/untarjs.wasm` (mambajs-core's own
  copy would look for `./unpack-*.wasm` relative to the page). The packages
  `python` / `pyjs` are never replaced by `installPackages`.
- Returns the existing Module (`exec`, `eval`, `exec_eval`,
  `async_exec_eval`, `to_js`, ...) + `installPackages(specs)`; the
  `bootstrap_from_empack_packed_environment` / `init_phase_*` API stays as is.
- Tests: `build_utils/npm_smoke_test.py` (pages in
  `build_utils/npm_smoke_test/`): every entry x (main thread, module worker),
  offline and with `--network` (numpy + `installPackages(["six"])`), the
  package served under another path than the test page (like a CDN).
- CI: `.github/workflows/npm.yml` builds + tests (all browsers), publishes on
  release tags (`4.1.0`, must equal the package version) / manual dispatch
  (secret `NPM_TOKEN`, variable `NPM_PACKAGE_NAME`). Manual publish:
  `cd build_root/npm/package && npm publish --access public`.
- On jsDelivr import `dist/index.js` directly, not `/+esm` (re-bundling
  breaks the `import.meta.url` asset paths).
- Assets (`assets/untarjs.wasm`, `assets/<arch>/`: runtime + packed env) are
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
  in the untarjs glue).
- `build_utils/npm_bundler_test.py` (part of `npm --test`,
  `NPM_TEST_BUNDLERS=0` skips it): vite, webpack, rollup, esbuild, parcel,
  each self-hosted (`copy-assets`) and with the CDN fallback (`cdnUrl` ->
  a local route, the package is not published yet); projects in
  `build_root/npm/bundler_test/<bundler>/` install the built `.tgz`.

## Benchmarks (`benchmarks/`)

pytest-benchmark cannot await in the browser, so `benchmarks/harness.py` is a
small async-aware replacement (`benchmark(fn, *args)`,
`await benchmark.aio(coro_fn, *args)`, `ops=` for loops inside JS).
`benchmarks/main.py` discovers `bench_*` functions in `bench_*.py` and prints a
`PYJS_BENCH_RESULT_JSON:` line which build_local.sh extracts (files written in
the browser FS do not reach the host). Compare runs via the stored json files;
pure-JS benchmarks (`raw_js_*`) show the run-to-run noise.

## Docs (`docs/`, Sphinx)

- Sphinx + myst-parser (markdown pages) + pydata-sphinx-theme + sphinx-autoapi
  (parses `module/` and `stubs/` statically: `pyjs_core` / `js` only exist in
  the browser). Docstrings are markdown flavoured, converted in `docs/conf.py`
  (fences / inline code) + napoleon (google sections).
- JupyterLite via jupyterlite-sphinx: `examples/*.py` / `*.js` become notebooks
  (jupytext).
- Two independent JupyterLite deployments: `lite/` (wasm32, built by
  jupyterlite-sphinx) and `lite64/` (wasm64, `jupyter lite build` in
  build_local.sh after sphinx, own lite dir). One deployment with both kernel
  envs (jupyterlite-xeus multi-env) crashed the wasm64 kernel ("memory access out
  of bounds" in the worker's initialize). `build_local.sh docs` builds pyjs +
  xeus-python for each of `ARCHS` (`ARCHS=wasm32` skips wasm64), then
  sphinx + lite64. docs/conf.py writes the jupyterlite configs
  (`docs/_generated/jupyter_lite_config{,_wasm64}.json`).
- Python kernel: xeus-python is **built from source** against the pyjs from this
  repo (`build_local.sh docs`), the env building it must **not** contain the conda packages
  `pyjs` / `pyjs-dev` / `libpyjs-static` (build_local.sh checks this). The pyjs
  python module is mounted from `module/pyjs` (`XeusAddon.mounts`), since only
  conda package files are packed from the prefix.
- JavaScript kernel: `jupyterlite-javascript-kernel==0.4.0a5` (pre-release, pip;
  0.3.0 has no top level await / iframe runtime). The pyjs runtime + a packed
  env (deploy env + `module/pyjs`) are deployed as
  `<html root>/pyjs-runtime/{wasm32,wasm64}/` (`html_extra_path`); the JS tour
  uses wasm64 when memory64 validates (override: `globalThis.PYJS_WASM`).
  Locating it from a cell (see `examples/js_api_tour.js`):
  IFrame runtime -> `document.baseURI` is the JupyterLite page
  (`lite/<app>/index.html`); Web Worker runtime (module worker, no
  `importScripts`) -> `location` is under `lite/extensions/`. The classic
  `pyjs_runtime_browser.js` is loaded via `fetch` + indirect `eval`.
- `build_utils/docs_smoke_test.py` (via `docs --test`): serves the html and
  runs, in lite/ and lite64/, the xpython REPL (+ `run_sync` with JSPI) and the
  `examples/run_sync.py` notebook, plus the whole JS tour (IFrame with the wasm32
  and the wasm64 runtime, Web Worker).
- xeus-javascript is not used anymore.

## CI

- `.github/workflows/main.yml`: matrix wasm32/wasm64 x chromium/firefox/webkit,
  dev env (`environment-dev.yml`, incl. pyjs-code-runner 3.3.0 from its git
  tag) from `setup-micromamba` (cached) -> `BUILD_ENV_PREFIX` ->
  `./build_local.sh test <wasm>`, again with `DISABLE_JSPI=1`, plus a
  `TEST_ENV=no-numpy` run. Jobs have a timeout (a failed suspension hangs).
- `.github/workflows/docs.yml`: `./build_local.sh docs --test`,
  deploys `docs_build/html` to GitHub Pages from `main`.
