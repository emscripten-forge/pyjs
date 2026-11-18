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
# test <arch> [browsers] [modes] [test_env] [jspi]
pixi run test wasm32 chromium main no-numpy     # without numpy
pixi run test wasm32 chromium "main worker" default off   # JSPI switched off
```

`test` builds the npm package of that architecture and runs the suite on it;
`test-npm` runs it on both architectures, tests the `lock` CLI and runs the
suite on apps built with the bundlers. Browsers: `chromium`, `firefox`,
`webkit` (the engine of Safari); modes: `main`, `worker`. One test suite
(`tests/`), run inside the browser by `tests/main.py`:

| | | |
|---|---|---|
| `tests/js/test_*.js` | JavaScript tests of the Module API | ES modules, every exported `test_*(pyjs)` |
| `tests/async/test_*.py` | async Python tests | own runner (pytest cannot await in the browser) |
| `tests/sync/test_*.py` | sync Python tests | pytest |
| `tests/npm/test_*.py` | the npm package: installs, archives, cache, progress, channels | own runner |

It runs on **pages**, each a different way of loading pyjs, all with the same
harness. `pyjs_test_driver` (in this repository) creates and runs them:

```bash
# kinds: npm, vite, webpack, rollup, esbuild, parcel
python -m pyjs_test_driver build-page <kind> --out <dir> ...

# every browser x mode, then a summary
python -m pyjs_test_driver run <dir> --browser chromium firefox \
    --mode main worker [--disable-jspi]
```

- `npm`: the npm package; the test packages are solved and installed at
  runtime, a package of the driver's test channel is pinned
- the bundler pages: an app around the npm package, built with that bundler

A page dir only has to follow a small contract: `index.html` reads its options
from the url, brings up pyjs, runs the suite with the shared
`pyjs_test_driver/web/harness.js` and sets `window.__pyjs_result`. `run` serves
the page dir together with `tests/` and drives the browser (playwright).

## Benchmarks

```bash
pixi run bench wasm32
# bench <arch> [browsers] [modes] [filter]
pixi run bench wasm32 "chromium firefox" "main worker" async
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
`build_root/benchmarks/<wasm>/<time>_<browser>_<mode>.json`. They run
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
