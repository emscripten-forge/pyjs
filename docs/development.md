# Development

Everything (environments, build, tests, benchmarks, docs) goes through
`build_local.sh`, which is also what the CI runs. It only needs
[micromamba](https://mamba.readthedocs.io) (or mamba).

```bash
./build_local.sh [wasm32|wasm64] [--fresh] [--test] [--bench] [--docs]
```

All environments and build directories live in `build_root/`:

| directory | environment file | content |
|---|---|---|
| `build_prefix_<wasm>` | `environment-wasm-build-<wasm>.yml` | native tools: emscripten, cmake, pyjs-code-runner, sphinx, ... |
| `host_prefix_<wasm>` | `environment-wasm.yml` | emscripten env pyjs is built against and installed into |
| `deploy_prefix_<wasm>` | `environment-wasm-deploy.yml` | emscripten env the tests / benchmarks run in |
| `build_<wasm>` | | cmake build directory |

`--fresh` deletes and recreates them.

## Tests

```bash
./build_local.sh wasm32 --test
BROWSERS="chromium firefox webkit" ./build_local.sh wasm64 --test
```

The tests in `tests/` run in the browser via
[pyjs-code-runner](https://github.com/emscripten-forge/pyjs-code-runner), in the
browser main thread and in a web worker (`BACKENDS`), in all browsers listed in
`BROWSERS` (`chromium`, `firefox`, `webkit`, the latter is the engine of Safari).
`tests/main.py` first runs the `async` tests in `tests/atests` and then the
(synchronous) pytest tests in `tests/tests`.

## Benchmarks

```bash
./build_local.sh wasm32 --bench
BENCH_FILTER=async BROWSERS="chromium firefox" ./build_local.sh wasm32 --bench
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
./build_local.sh wasm32 --docs
```

builds pyjs, builds [xeus-python](https://github.com/jupyter-xeus/xeus-python)
from source against it and uses it as the kernel of the JupyterLite embedded in
these docs (built with Sphinx and
[jupyterlite-sphinx](https://jupyterlite-sphinx.readthedocs.io)). The html ends
up in `build_root/docs_html`.
