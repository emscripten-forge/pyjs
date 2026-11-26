# pyjs

Python <-> JavaScript FFI for emscripten/wasm Python. pyjs 6: the core is
nanobind (only for the module `pyjs_core`) + plain wasm exports + EM_JS, no
pybind11 / embind (except `src/extract.cpp` of the runtime). API = PEP 818 /
pyodide. C++ in `src/` (`slot.hpp`, `js_proxy.cpp`, `deep.cpp`, `py_entry.cpp`,
`module.cpp`, `stack_switching.c`), the JS half in `src/js/*.ts` (bundled by
esbuild and embedded into libpyjs by `build_utils/embed_js.cmake`: no
`--pre-js` / `--post-js` files), Python module in `module/pyjs/`, type stubs
of `pyjs_core` for the docs in `stubs/`.
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
# test <arch> [browsers] [modes] [jspi|no-jspi]
pixi run test wasm32 chromium "main worker" no-jspi  # JSPI switched off at runtime
pixi run bench wasm32 [browsers] [modes] [filter]          # benchmarks
pixi run docs [out dir]                      # npm package + sphinx docs
pixi run docs-serve [port]                   # sphinx-autobuild: rebuild + live reload (no npm build)
pixi run npm-package [archs]                 # npm package (default wasm32 + wasm64)
pixi run test-npm [browsers]                 # npm package + both archs, lock CLI, bundlers
pixi run clean                               # rm -rf build_root (envs stay)
pixi run example-embed [archs]               # examples/embed (own pixi project): libpyjs of the build tree in a MAIN_MODULE, node
pixi run example-npm-page                    # examples/npm-page: plain page + packed package, chromium
```

`examples/` are small projects as a user has them, run with the pyjs of the
repository (CI: `example-embed` in the build job, `example-npm-page` in the
bundlers job). An embedder must link a `MAIN_MODULE` (otherwise libpyjs, with
its embedded JS, is dropped by the linker: nothing in the program calls it).

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
for side modules. Tests: `tests/test_webgpu.py` (in the runtime),
`tests/test_webgpu_device.py` (adapter / device; skips without `navigator.gpu` or
adapter, the usual case headless).

WebGL2 / SDL2: `MAIN_MODULE=1` implies `INCLUDE_FULL_LIBRARY`, so emscripten's
GL JS is always in the runtime, but only at WebGL1 level. cmake options
`PYJS_WEBGL` (`-lGL -sMAX_WEBGL_VERSION=2 -sFULL_ES3`) and `PYJS_SDL2`
(`-sUSE_SDL=2`, port downloaded on first use), both default ON, link them
**only into the runtime** (`PRIVATE` on `pyjs_runtime_browser`, not INTERFACE:
downstream executables like xeus-python are not forced to). Side modules
(imgui-bundle, ctypes / PyOpenGL via `ctypes.CDLL(None)`) resolve GL / SDL from
the main module. Python: `pyjs.set_canvas(canvas)` (`Module.canvas` +
`specialHTMLTargets["#canvas"]`, `Module._set_canvas` in `src/js/runtime.ts`),
`pyjs.request_animation_frame_loop(cb)` (`emscripten_request_animation_frame_loop`,
`src/module.cpp`). Tests: `tests/test_webgl.py` (context via
ctypes; skips without WebGL2), `tests/test_animation_frame.py`.

Memory: the runtime is linked with `-sMAXIMUM_MEMORY` = 4GB (wasm32) / 16GB
(wasm64) (cmake cache var `PYJS_MAXIMUM_MEMORY`; emscripten's default is 2GB, also
for wasm64). `tests/test_memory.py` allocates beyond 2 GiB / 4 GiB and
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
- `CMakeLists.txt` needs `esbuild` on PATH (bundles `src/js/index.ts`, then
  `build_utils/embed_js.cmake` turns the bundle into `pyjs_js.cpp`): it is in
  the dev env, as in every task.
- empack finds its default config via `sys.prefix.startswith(CONDA_PREFIX)`.
- A build dir configured with another toolchain path (e.g. an old env) gets
  its cmake cache reset on the next configure ("You have changed variables
  that require your cache to be deleted"): harmless, it reconfigures.

## Tests

- One suite (`tests/`), run inside the browser by `tests/main.py`
  (`async def main(options) -> dict`): ONE `pytest.main()` over
  `tests/test_*.py`; `async def` tests are collected and awaited afterwards
  (`tests/pytest_async.py`, no fixtures with cleanup for them);
  `tests/js/test_*.js` (ES modules, exported `test_*(pyjs)`, run by
  `tests/test_js.py`); `tests/pyodide/` = pyodide's suite adapted (xfail =
  what pyjs lacks). Options: `filter` (-k), `file`, `runxfail`. Helpers:
  `tests/helpers.py`. The download tests fetch `/test-data/all_bytes.bin`,
  generated by the driver (no binaries in the repo; absolute path: works on
  every page / worker).
- pytest cannot run async tests in the browser: `pytest.main()` is synchronous and
  the browser event loop cannot be blocked (`WebLoop.run_until_complete` just
  schedules without JSPI). Hence `tests/pytest_async.py`: `async def` tests
  are collected, then awaited after `pytest.main()` returned.
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
- The npm package loads the runtime as ES module = strict mode (a classic
  script embedding is sloppy mode: both must work). Type check of the JS
  half (the cmake build only bundles, esbuild does not type check): `pixi run
  node npm/node_modules/typescript/bin/tsc --noEmit --strict --target es2022
  --lib es2022,dom src/js/index.ts src/js/emscripten.d.ts`.
- A dead page (wasm trap, "Maximum call stack size exceeded" thrown through
  Python) never reports a result: the driver gives up after 5 min of silence
  (`SILENCE_S`). Tests expected to crash an unfixed build: run them alone
  first (`--option filter=<name>`). Test helpers for leaks / GC:
  `tests/helpers.py` (`handle_count`, `pyproxy_count`, `require_js_gc`:
  chromium runs with `--expose-gc`), `requires_jspi`. JSPI tests must
  `pytest.skip`, never `return`.
- The test runner itself is tested: `tests/test_pytest_async.py` (XPASS,
  xfail arguments, skip, per-test timeout).
- Tests must pass in the main thread *and* in a worker, and in chromium,
  firefox and webkit.
- npm / bundler pages need the network (mambajs fetches from prefix.dev,
  which sometimes answers without CORS headers): `run --retries 5` (10 s
  apart, `--retry-delay`) reruns a
  page whose *setup* failed (`{ok: false, error}`, no test ran), never failed
  tests. Vanilla pages are offline, no retries.
- No assertions that depend on timing (CI runners are slow and noisy): make the
  order explicit (e.g. a JS promise the test resolves itself), check structure
  instead of speed (`_CountSetTimeout` in `tests/test_webloop.py`: the
  fast path uses no `setTimeout`), only lower bounds for delays ("at least"),
  and timeouts only as hang guards. Speed belongs in `benchmarks/`.

## How JS and Python call each other

(The long version with diagrams: `docs/design.md`; the headers of the source
files explain the rest.)

Everything crosses as **slots** (`src/slot.hpp`, `src/js/codec.ts`): 16 bytes
(tag, aux, double / 2 ints); only addresses of slots are passed, each
operation is ONE hop. Pointers travel as `double` (same code on wasm64). JS
objects are **handles** (index into a JS table, `hNew` / `hGet` / `hFree`).
Errors never cross as exceptions: return code + the thrown value / exception
in the result slot. **Who owns what in a slot is asymmetric**: the table "WHO
OWNS WHAT IS IN A SLOT" in `slot.hpp` (read it before touching encode /
decode / to_slot / from_slot; most lifetime bugs of the review came from it).

JS -> Python: `PyProxy` = ES `Proxy` + one handler (`src/js/pyproxy.ts`);
traps / methods call the wasm exports of `src/py_entry.cpp`: `pyjs_call`
(args encoded into the scratch region, 64 KiB, malloc beyond), `pyjs_op`
(getattr / setitem / len / iter / hasattr ..., `PyOp`), `pyjs_call_promising`
(JSPI). A Python exception -> 3 result slots -> `PythonError`. Results that
point into a Python object are kept alive by `g_keep` (sync) / `out[3]`
(promising). Owned proxies: `destroy()` or FinalizationRegistry backstop;
borrowed proxies (arguments of a Python -> JS call) die with the call.
`Module.runPython` / `runPythonAsync` / `pyimport` / `globals` / `toPy`
(`src/js/runtime.ts`) are thin wrappers around `pyjs.code` functions.

Python -> JS: `JSProxy` (`src/js_proxy.cpp`): CPython heap types, one per
set of ability flags (`JsFlag`), with Python mixins (`module/pyjs/_proxy_types.py`:
`JSArray`, `JSMap`, ...) chosen by the hook `proxy_mixins`. Operations go
through EM_JS one-liners `pyjs_js_*` -> `pyjsCore.<fn>` (`src/js/index.ts`,
implemented in `src/js/jsops.ts`). **No function of jsops.ts may throw** (a
JS exception through CPython's wasm frames is fatal): catch + `fail()`.
A thrown JS value -> hook `raise_js_error` -> `JSException`
(`module/pyjs/error_handling.py`, also a `RuntimeError`). Hooks: Python
objects handed to the core once by `pyjs_core.set_hooks`
(`module/pyjs/__init__.py`, positional: order must match `module.cpp`).

Deep conversion `to_py` / `to_js` (`src/deep.cpp`, `src/js/deep.ts`): the
whole structure as ONE stream of slots in one hop; **recursive, at most
`MAX_NESTING = 200` levels** (RecursionError; a WebKit worker's call stack
ends at ~500); containers that change during the walk -> RuntimeError;
nested conversions (a getter / `__hash__` converting something) get their
own stream blocks. With options (`pyproxies`, `dict_converter`, converters)
the step-by-step Python path in `module/pyjs/convert.py` runs instead: a
second implementation, keep both in sync.

Every asyncio task step is a JS -> Python call from a JS event (webloop:
MessageChannel / setTimeout -> `callPromising` with JSPI). `jspi.depth`
counts the running JS -> Python entries (incl. `SyncEntry` in `module.cpp`
for the main loop / rAF callbacks and `release()` for decrefs): a task is
only started at depth 0.

Other names of the package: `js`, `jstypes.*`, `pyodide.ffi` / `pyodide.code`
(`module/pyjs/_modules.py`).

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
- Tests: `tests/test_webloop.py`.

## JSPI (`pyjs.run_sync` / `can_run_sync`)

- **One build for all browsers**: no `-sJSPI`. JSPI is used when the browser
  has `WebAssembly.Suspending` / `WebAssembly.promising` (`pyjs.jspi_enabled()`),
  otherwise pyjs behaves as without it (`can_run_sync()` False, `run_sync`
  raises, urllib3 falls back to XHR). Same pattern as pyodide.
- Suspend point: `EM_JS pyjs_js_await` (`src/js_proxy.cpp`), its JS replaces
  the import with `new WebAssembly.Suspending(...)` before instantiation if
  supported. Entry point: the plain wasm export `pyjs_call_promising`
  (`src/py_entry.cpp`), wrapped with `WebAssembly.promising` at runtime; JS
  side `callPythonPromising` (`src/js/pyproxy.ts`), state in `src/js/jspi.ts`.
  The webloop enters task steps through it, so `run_sync` works in asyncio
  tasks, also in xeus-python cells (they run as coroutines).
- Suspending only works with **no JS frame** between the promising entry and the
  suspend point. **Any number of suspended Python stacks** (ported from pyodide
  314.0.8, MPL-2.0, `src/stack_switching_README.md`): each promising call is a
  task; `src/stack_switching.c` swaps the per-task part of the one CPython
  thread state (frames, datastack, exc state, context, asyncio running task),
  `src/js/stack_state.ts` evicts / restores the C stack data of suspended tasks.
  `run_sync` = `pyjs_js_await` (Suspending; `jspiAwait` captures the state)
  then `pyjs_js_resume` (`jspiResume` restores it from inside the resumed wasm,
  before `out` on the task's C stack is written). Tasks are only entered at
  the event loop level: `callPythonPromising` waits a macrotask if
  `jspi.depth > 0` (pyodide does the same). `pyjs_call_promising` hands the
  result keep-alive to JS in `out[3]` (not the global `g_keep`).
  `can_run_sync()` = JSPI enabled and the innermost entry is a promising one
  (False in sync JS callbacks). `run_until_complete` blocks via `run_sync`
  where possible. Tests: `tests/test_stack_switching.py` (deterministic: the
  test resolves the promises), `tests/pyodide/test_pyodide_stack_switching.py`;
  `Module._jspi_suspended_count()` / `_jspi_stack_state_count()` for checks.
  Open: `run_sync` inside `to_js` / `to_py` converters is not blocked.
- Tests: `pixi run test <wasm> <browsers> "main worker" no-jspi` switches JSPI off at
  runtime (`run --disable-jspi` -> option `disable_jspi` ->
  `pyjs.core._disable_jspi()` in `tests/main.py`), CI runs both. A browser without the APIs at all can be
  simulated with playwright: `delete WebAssembly.Suspending` in an init script.
  `tests/test_jspi.py` (async: run_sync needs a task step).
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
- Init (since pyjs 5): the core (libpyjs) never fills the file system or
  preloads shared libs; whoever fills it calls `Module.startPython()` (synchronous)
  (`src/js/runtime.ts`: python version from the export `pyjs_python_version`,
  error without `/lib/pythonX.Y`, idempotent). The classic API (`bootstrap_from_empack_*`,
  `init_phase_*`, `_untar`, `_install_conda_file`, untar/inflate C++,
  `load_pkg.js`, `dynload.js`, `fetch.js`) is gone. The runtime target
  (not libpyjs) has `src/extract.cpp`: `Module._extract_archive(bytes, dest,
  {conda, meta, rename})` on libarchive (tar / zip, gzip / bzip2 / zstd, no
  xz; .conda = zip of pkg-/info-*.tar.zst), own write loop (no `..` /
  absolute paths / writes through the archive's symlinks; hard links ->
  copies), returns `{files, sharedLibs, meta}`. Tests: `tests/test_extract.py`.
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
  the package, saved (units whose `__pycache__` entry counts grew) only on
  `Module.saveBytecode()` and, best effort, on `visibilitychange` -> hidden
  (main thread): no interval since 5.2 (periodic readdirs of every
  `__pycache__` = unpredictable cost). Valid because the extraction keeps
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
  `{url, sha256?}`), `archives`, `files`, `stdlib`, `cache`, `verifySha256`,
  `onProgress`, `wasmModule`, `env`. `python` / `pyjs` are never replaced.
- Optional stdlib (split python recipe: python-ssl / -sqlite3 / -lzma /
  -cjkcodecs / -test-modules = side modules in lib-dynload):
  `build_utils/npm_env_meta.py` marks them `optional` in the env meta; shipped
  but only extracted on request (option `stdlib: [...] | "all"`,
  `installPackages(["sqlite3"])`: shipped tarball, no solve). The solver's lock
  lists them as installed (never downloaded from a channel). With a python
  that has them built in there are none (`stdlib` is a no-op).
  `tests/test_stdlib.py`.
- Licenses: `build_utils/third_party_licenses.py` (task `pack`) writes
  `assets/<arch>/THIRD_PARTY_LICENSES.md`: the `info/licenses` of the host
  env's `*-static` packages + nanobind (linked into the runtime) and of every
  shipped package (via `extracted_package_dir` in conda-meta), plus
  emscripten's libc / libc++ / compiler-rt / ports.
- The runtime links libsqlite3 / libssl / libcrypto / liblzma only if
  libpython has the module built in (`pyjs_link_if_builtin` in
  CMakeLists.txt): a split python has them as side modules with their own copy.
- Returns the Module + `installPackages(specs | pinned)`, `unpackArchive`,
  `addFiles` (serialized in a queue). Entries also export `compileRuntime()`.
  CLI: `npx <pkg> lock <specs>` (`src/lock.ts`, bundled for node into
  `bin/lock.mjs`) -> `{wasm32: [{url, sha256}], ...}`; the docs build pins the
  playground's numpy with it (`pyjs-lock.json`).
- Tests: the full test suite on npm pages (both archs x main / worker) and on
  the 5 bundler pages (see Tests). npm-only tests (`test_install.py`,
  `test_channel.py`, ...) skip themselves when the Module has no
  `installPackages` (`pytestmark = skipif`); `test_install.py`: pinned at
  init / runtime, `.conda`, relocation, replacing, sha256, cache, bytecode
  cache, progress, `compileRuntime`.
  `tests/test_channel.py` installs from a self-hosted channel (static
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
  `cache: true` (5.1, opt-in: archive URLs may change content) caches an
  archive like a package: unpacked tar in `pyjs-packages-v2` + bytecode,
  key = URL + `?pyjs-archive-path=<path>` (`loadArchive` / `installArchive`
  in `runtime.ts`); bypassed with `verifySha256` + sha256.
  Tests: `tests/test_archives.py` with archives the driver generates
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
  The runtime wasm (~14 MB) is fetched normally, caching is left to the
  browser's HTTP cache (deliberately not in Cache Storage). A dev server
  without ETag / cache headers answers 200 on every reload (seen in webgym:
  once per page with `compileRuntime`); CDN / `immutable` headers give a
  cache hit. A Cache Storage copy would need the package version in its key
  (`copy-assets` paths are not versioned).
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
- `.github/workflows/npm.yml`: job `build` (`pixi run npm-package`,
  `test-lock`), then a matrix wasm32/wasm64 x chromium/firefox/webkit:
  `pixi run run-tests <wasm> <browser>`, again with `no-jspi`; job
  `bundlers` (`test-bundlers`). Jobs have a timeout (a failed suspension
  hangs). Publishes the package on release tags.
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
