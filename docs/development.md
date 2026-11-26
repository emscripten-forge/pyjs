# Development

Everything (environments, build, tests, benchmarks, docs) goes through
[pixi](https://pixi.sh) tasks (`pixi.toml`, pixi >= 0.84), which is also what
the CI runs:

```bash
pixi run build wasm32          # wasm32 | wasm64 | "wasm32 wasm64"
pixi run test wasm32           # npm package of this arch + the tests
pixi run bench wasm32
pixi run npm-package           # wasm32 + wasm64
pixi run test-npm              # + its full test
pixi run docs
pixi task list                 # all tasks with a description
```

The steps are tasks depending on each other: `envs` → `configure` → `build`
→ `pack` → `npm-package` → `test-page` → the tests. The environments
(`pixi.lock`, in `.pixi/envs/`):

| environment | content |
|---|---|
| `default` | native tools, one env for wasm32 and wasm64: emscripten, cmake, empack, node, playwright, sphinx |
| `host-<wasm>` | emscripten env pyjs is built against (incl. libarchive for the runtime's extractor) |
| `npm-env-<wasm>` | python + stdlib shipped in the npm package |

The emscripten environments cannot run on the build machine: the task `envs`
installs them with `pixi install --platform emscripten-<wasm>`. Build output
goes to `build_root/` (`build_<wasm>/` = cmake build dir, `npm/`, `pages/`,
...); `pixi run clean` deletes it. To work by hand (node / npm, empack,
playwright, ...): `pixi shell`.

A local recipe build (e.g. a new python from emscripten-forge/recipes): put
its output dir first in `channels` of `pixi.toml`, then `pixi run ...`
(re-solves `pixi.lock`).

## Tests

```bash
pixi run test wasm32
pixi run test wasm64 "chromium firefox webkit"
# test <arch> [browsers] [modes] [jspi|no-jspi]
pixi run test wasm32 chromium "main worker" no-jspi   # JSPI switched off
```

`test` builds the npm package of that architecture and runs the suite on it;
`test-npm` runs it on both architectures, tests the `lock` CLI and runs the
suite on apps built with the bundlers. Browsers: `chromium`, `firefox`,
`webkit` (the engine of Safari); modes: `main`, `worker`. Every test must pass
in all of them, and with JSPI switched off.

One test suite (`tests/`), and the whole pytest session runs **inside the
browser**: `tests/main.py` is started on the page and runs `pytest.main()`
over `tests/`:

| | |
|---|---|
| `tests/test_*.py` | the tests of pyjs. Plain functions are normal pytest tests. `async def` tests are collected by pytest too, but awaited after `pytest.main()` returned (pytest cannot await inside the browser, see `tests/pytest_async.py`); fixtures with cleanup do not work for them |
| `tests/js/test_*.js` | JavaScript tests (ES modules, every exported `test_*(pyjs)` function), run as pytest tests by `tests/test_js.py` |
| `tests/pyodide/` | pyodide's test suite (release 314.0.8, MPL-2.0), adapted to pyjs: the API follows pyodide / PEP 818. What pyjs does not have is kept as `xfail` with the reason, see `tests/pyodide/README.md` |

Tests of the npm package (`test_install.py`, `test_channel.py`, ...) skip
themselves on pages without it. Shared helpers: `tests/helpers.py`. No test
depends on timing (CI runners are slow): the order is made explicit, e.g. with
a promise the test resolves itself (`tests/test_stack_switching.py`); speed
belongs in the benchmarks.

It runs on **pages**, each a different way of loading pyjs, all with the same
harness. `pyjs_test_driver` (in this repository) creates and runs them:

```bash
# kinds: npm, vite, webpack, rollup, esbuild, parcel, pyodide
python -m pyjs_test_driver build-page <kind> --out <dir> ...

# every browser x mode, then a summary
python -m pyjs_test_driver run <dir> --browser chromium firefox \
    --mode main worker [--disable-jspi]

# only some tests (a pytest -k expression / one file), xfail tests as normal ones
python -m pyjs_test_driver run <dir> --option filter=test_proxy_types
python -m pyjs_test_driver run <dir> --option file=pyodide/test_pyodide_jsproxy.py
python -m pyjs_test_driver run <dir> --option runxfail=1
```

- `npm`: the npm package; the test packages are solved and installed at
  runtime, a package of the driver's test channel is pinned
- the bundler pages: an app around the npm package, built with that bundler
- `pyodide`: a pyodide release, for the reference benchmarks
  (`pixi run bench-pyodide`)

A page dir only has to follow a small contract: `index.html` reads its options
from the url, brings up pyjs, runs the suite with the shared
`pyjs_test_driver/web/harness.js` and sets `window.__pyjs_result`. `run` serves
the page dir together with `tests/` and drives the browser (playwright).

## Examples

`examples/` holds small projects as a user of pyjs has them, run with the
pyjs of the repository (the CI runs both):

```bash
pixi run example-embed         # examples/embed: libpyjs in a program of its own (node)
pixi run example-npm-page      # examples/npm-page: a plain page with the packed package (chromium)
```

`examples/embed` is a pixi project of its own (its own environments), only
`libpyjs` comes from the build tree. `example-npm-page` needs the packed
package (`pixi run npm-package`).

## Benchmarks

```bash
pixi run bench wasm32
# bench <arch> [browsers] [modes] [filter]
pixi run bench wasm32 "chromium firefox" "main worker" async
# the same benchmarks on pyodide (the reference, wasm32 only)
pixi run bench-pyodide chromium worker
```

The benchmarks in `benchmarks/` measure the Python ↔ JavaScript FFI and the
asyncio event loop (`pyjs.WebLoop`). They use a small async-aware harness
(`benchmarks/harness.py`, similar to pytest-benchmark, which cannot be used
since it cannot await in the browser):

```python
def bench_call_int_arg(benchmark):
    f = pyjs.js.Function("a", "return a")
    benchmark(f, 1)

async def bench_asyncio_sleep_0(benchmark):
    await benchmark.aio(asyncio.sleep, 0)
```

The results are stored in
`build_root/benchmarks/<wasm>/<time>_<browser>_<mode>.json` (pyodide:
`build_root/benchmarks/pyodide/`). They run
on the npm page (`pyjs_test_driver run ... --entry benchmarks`).
`python benchmarks/report.py <json>...` turns them into markdown tables; the
CI (`.github/workflows/bench.yml`) runs the benchmarks for every architecture
and browser and shows these tables on the summary page of each job.

## Documentation

```bash
pixi run docs                  # docs [out dir], default build_root/docs_html
```

builds the npm package (deployed next to the html, the <a href="playground/index.html">playground</a>
loads it), pins the playground's packages (`pyjs-lock.json`, no solver in the
browser) and builds the docs with Sphinx.

While writing docs:

```bash
pixi run docs-serve            # docs-serve [port], default 8000
```

serves the docs at `http://127.0.0.1:8000` and rebuilds them on every change
(`docs/` and the docstrings in `module/` / `stubs/`), the browser reloads by
itself (`sphinx-autobuild`). Only Sphinx runs, no npm package build: the
playground and the run buttons use the package of the last `pixi run docs`.
