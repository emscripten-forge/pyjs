# pyjs
[![CI](https://github.com/emscripten-forge/pyjs/actions/workflows/main.yml/badge.svg)](https://github.com/emscripten-forge/pyjs/actions/workflows/main.yml)
[![docs](https://img.shields.io/badge/pyjs-docs-yellow)](https://emscripten-forge.github.io/pyjs/)

pyjs is a Python <-> JavaScript foreign function interface (FFI) for
wasm/emscripten compiled Python (core: [nanobind](https://github.com/wjakob/nanobind)
+ TypeScript). The API follows [PEP 818](https://peps.python.org/pep-0818/)
and the FFI of [pyodide](https://pyodide.org/en/stable/usage/type-conversions.html):
code written for pyodide runs unchanged.

* Python 3.14, emscripten 6, `wasm32` and `wasm64`
* runs in the browser main thread and in web workers
* asyncio support: `await` JavaScript promises from Python and Python
  coroutines from JavaScript
* `run_sync` (JSPI): synchronous Python code waits for a promise, any number
  of Python stacks at the same time
* tested in Chromium, Firefox and WebKit (Safari)
* distributed via [emscripten-forge](https://github.com/emscripten-forge/recipes)

## Documentation



See the [documentation](https://emscripten-forge.github.io/pyjs/).
Or go directely to the [playground](https://emscripten-forge.github.io/pyjs/playground/index.html) to try it out.


## Quickstart

Access JavaScript from Python:

```python
import pyjs

# hello world
pyjs.js.console.log("Hello, World!")

# create a JavaScript function to add two numbers
js_function = pyjs.js.Function("a", "b", """
    console.log("Adding", a, "and", b)
    return a + b
""")

# call the function
result = js_function(1, 2)
```

Access Python from JavaScript:

```javascript
// hello world
pyjs.runPython("print('Hello, World!')");

// run python code and get the value of its last line
const py_list = pyjs.runPython("[i * i for i in range(10)]");

// access
console.log(py_list.get(3)); // 9, same as py_list[3] on the python side
py_list.destroy();
```

## Development

Building, testing, benchmarking and building the docs all go through
[pixi](https://pixi.sh) tasks (only pixi >= 0.84 is needed), the CI runs the
same tasks:

```bash
pixi run build wasm32                   # build pyjs
pixi run test wasm64                    # build + run the tests in the browser
pixi run test wasm32 "chromium firefox webkit"
pixi run bench wasm32                   # FFI / asyncio benchmarks
pixi run docs                           # sphinx docs + playground
pixi run npm-package                    # npm package
```

See [development](https://emscripten-forge.github.io/pyjs/development.html)
for details.
