# Development

Everything (environments, build, tests, benchmarks, docs) goes through
`build_local.sh`, which is also what the CI runs. It only needs
[micromamba](https://mamba.readthedocs.io) (or mamba).

```bash
./build_local.sh build|test|bench wasm32|wasm64 [--fresh]
./build_local.sh docs|npm [--test] [--fresh]
```

All environments and build directories live in `build_root/`:

| directory | environment file | content |
|---|---|---|
| `dev_prefix` | `environment-dev.yml` | native tools, one env for wasm32 and wasm64: emscripten, cmake, node, pyjs-code-runner, sphinx, ... |
| `host_prefix_<wasm>` | `environment-host.yml` | emscripten env pyjs is built against and installed into (+ what the docs need to build xeus-python) |
| `deploy_prefix_<wasm>` | (package list in `build_local.sh`, `TEST_ENV`) | emscripten env the tests / benchmarks run in |
| `build_<wasm>` | | cmake build directory |

`--fresh` deletes and recreates them. To work by hand (node / npm,
empack, playwright, ...) activate the dev env:
`micromamba activate build_root/dev_prefix`.

## Tests

```bash
./build_local.sh test wasm32
BROWSERS="chromium firefox webkit" ./build_local.sh test wasm64
```

The tests in `tests/` run in the browser via
[pyjs-code-runner](https://github.com/emscripten-forge/pyjs-code-runner), in the
browser main thread and in a web worker (`BACKENDS`), in all browsers listed in
`BROWSERS` (`chromium`, `firefox`, `webkit`, the latter is the engine of Safari).
`tests/main.py` first runs the `async` tests in `tests/atests` and then the
(synchronous) pytest tests in `tests/tests`.

## Benchmarks

```bash
./build_local.sh bench wasm32
BENCH_FILTER=async BROWSERS="chromium firefox" ./build_local.sh bench wasm32
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
`build_root/benchmarks/<wasm>/<stamp>_<browser>_<backend>.{log,json}`.

## Documentation

```bash
./build_local.sh docs
```

builds pyjs, builds [xeus-python](https://github.com/jupyter-xeus/xeus-python)
from source against it and uses it as the kernel of the JupyterLite embedded in
these docs (built with Sphinx and
[jupyterlite-sphinx](https://jupyterlite-sphinx.readthedocs.io)). The html ends
up in `build_root/docs_html`.
