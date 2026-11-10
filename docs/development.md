# Development

Everything (environments, build, tests, benchmarks, docs) goes through
`build_local.sh`, which is also what the CI runs. It only needs
[micromamba](https://mamba.readthedocs.io) (or mamba).

```bash
./build_local.sh build|test|bench wasm32|wasm64 [--fresh]
./build_local.sh npm [--test] [--fresh]
./build_local.sh docs [--fresh]
```

All environments and build directories live in `build_root/`:

| directory | environment file | content |
|---|---|---|
| `dev_prefix` | `environment-dev.yml` | native tools, one env for wasm32 and wasm64: emscripten, cmake, empack, node, playwright, sphinx |
| `host_prefix_<wasm>` | `environment-host.yml` | emscripten env pyjs is built against and installed into |
| `test_env_<name>_<wasm>` | (`TEST_PACKAGES` in `build_local.sh`, `TEST_ENV`) | emscripten env of the vanilla test pages |
| `build_<wasm>` | | cmake build directory |
| `pages/` | | test pages (see below) |

`--fresh` deletes and recreates them. To work by hand (node / npm,
empack, playwright, ...) activate the dev env:
`micromamba activate build_root/dev_prefix`.

## Tests

```bash
./build_local.sh test wasm32
BROWSERS="chromium firefox webkit" ./build_local.sh test wasm64
```

One test suite (`tests/`), run inside the browser by `tests/main.py`:

| | | |
|---|---|---|
| `tests/js/test_*.js` | JavaScript tests of the Module API | ES modules, every exported `test_*(pyjs)` |
| `tests/async/test_*.py` | async Python tests | own runner (pytest cannot await in the browser) |
| `tests/sync/test_*.py` | sync Python tests | pytest |

It runs on **pages**, each a different way of loading pyjs, all with the same
harness. `pyjs_test_driver` (in this repository) creates and runs them:

```bash
# kinds: vanilla, npm, vite, webpack, rollup, esbuild, parcel
python -m pyjs_test_driver build-page <kind> --out <dir> ...

# browsers: chromium, firefox, webkit; modes: main, worker
python -m pyjs_test_driver run <dir> --browser <browser> \
    --mode <mode> [--disable-jspi]
```

- `vanilla`: the raw runtime + an empack-packed env (the classic Module API,
  as projects using pyjs as a static library load it), `./build_local.sh test`
- `npm` and the bundler pages: the npm package, the test packages are
  installed at runtime via mambajs, `./build_local.sh npm --test`

A page dir only has to follow a small contract: `index.html` reads its options
from the url, brings up pyjs, runs the suite with the shared
`pyjs_test_driver/web/harness.js` and sets `window.__pyjs_result`. `run` serves
the page dir together with `tests/` and drives the browser (playwright).

Env vars: `BROWSERS` (`chromium`, `firefox`, `webkit`, the latter is the
engine of Safari), `MODES` (`main`, `worker`), `DISABLE_JSPI=1` (test like in
a browser without JSPI), `TEST_ENV=no-numpy`.

## Benchmarks

```bash
./build_local.sh bench wasm32
BENCH_FILTER=async BROWSERS="chromium firefox" \
    ./build_local.sh bench wasm32
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
`build_root/benchmarks/<wasm>/<stamp>_<browser>_<mode>.{log,json}`. They run
on the vanilla page (`pyjs_test_driver run ... --entry benchmarks`).

## Documentation

```bash
./build_local.sh docs
```

builds the npm package (deployed next to the html, the <a href="playground/index.html">playground</a>
loads it) and the docs with Sphinx. The html ends up in `build_root/docs_html`.
