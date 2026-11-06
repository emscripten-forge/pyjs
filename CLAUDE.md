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
./build_local.sh wasm32                      # build + install pyjs
./build_local.sh wasm32 --test               # + browser tests (main thread + worker)
BROWSERS="chromium firefox webkit" ./build_local.sh wasm64 --test
./build_local.sh wasm32 --bench              # benchmarks
BENCH_FILTER=async ./build_local.sh wasm32 --bench
./build_local.sh wasm32 --docs               # sphinx docs + jupyterlite
./build_local.sh wasm32 --docs --test        # + docs smoke test (instead of pyjs tests)
./build_local.sh wasm32 --fresh ...          # recreate envs / build dirs
```

Useful env vars: `BROWSERS` (chromium firefox webkit; webkit = Safari engine),
`BACKENDS` (browser-main browser-worker), `BENCH_FILTER`, `BUILD_ENV_PREFIX`
(use an existing build env, never deleted; CI), `DEPLOY_ENV_FILE`
(e.g. `environment-wasm-deploy-no-numpy.yml`), `PYJS_CODE_RUNNER_DIR` (local
pyjs-code-runner checkout, pip -e installed into the build env),
`PLAYWRIGHT_INSTALL_ARGS` (`--with-deps` on CI), `DOCS_OUT_DIR`, `DISABLE_JSPI=1`,
`EXTRA_CHANNELS` (channels searched first when creating envs).

Everything lives in `build_root/` (gitignored, never commit):

| dir | env file | |
|---|---|---|
| `build_prefix_<wasm>` | `environment-wasm-build-<wasm>.yml` | native: emscripten (`emscripten_emscripten-<wasm>`), cmake, pyjs-code-runner, sphinx, jupyterlite, ... |
| `host_prefix_<wasm>` | `environment-wasm.yml` | emscripten env pyjs is built against + installed into |
| `deploy_prefix_<wasm>` | `environment-wasm-deploy.yml` | env the tests / benchmarks run in |
| `host_docs_prefix_<wasm>` | `environment-wasm.yml` + `environment-wasm-docs.yml` | `--docs`: pyjs + xeus-python built from source (wasm32 + wasm64) |
| `build_<wasm>`, `build_docs_wasm32`, `build_xeus_python_wasm32` | | cmake build dirs |
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
- `PREFIX` must point to the host env *before* activating the build env: the
  emscripten activation script bakes it into `CMAKE_ARGS`. Activation scripts
  are not `set -u` safe (wrapped in `set +u`).
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
- Tests: `DISABLE_JSPI=1 ./build_local.sh <wasm> --test` switches JSPI off at
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
  of bounds" in the worker's initialize). `--docs` first runs
  `build_local.sh wasm64 --docs-kernel` (own process / build env activation);
  `DOCS_WASM64=0` skips wasm64. docs/conf.py writes the jupyterlite configs
  (`docs/_generated/jupyter_lite_config{,_wasm64}.json`).
- Python kernel: xeus-python is **built from source** against the pyjs from this
  repo (`--docs`), the env building it must **not** contain the conda packages
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
- `build_utils/docs_smoke_test.py` (via `--docs --test`): serves the html and
  runs, in lite/ and lite64/, the xpython REPL (+ `run_sync` with JSPI) and the
  `examples/run_sync.py` notebook, plus the whole JS tour (IFrame with the wasm32
  and the wasm64 runtime, Web Worker).
- xeus-javascript is not used anymore.

## CI

- `.github/workflows/main.yml`: matrix wasm32/wasm64 x chromium/firefox/webkit,
  build env from `setup-micromamba` (cached) -> `BUILD_ENV_PREFIX` ->
  `./build_local.sh <wasm> --test`, again with `DISABLE_JSPI=1`, plus a no-numpy
  run. Jobs have a timeout (a failed suspension hangs).
- `.github/workflows/docs.yml`: `./build_local.sh wasm32 --docs --test`,
  deploys `docs_build/html` to GitHub Pages from `main`.
