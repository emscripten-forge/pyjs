# pyjs
[![CI](https://github.com/emscripten-forge/pyjs/actions/workflows/main.yml/badge.svg)](https://github.com/emscripten-forge/pyjs/actions/workflows/main.yml)
[![docs](https://img.shields.io/badge/pyjs-docs-yellow)](https://emscripten-forge.github.io/pyjs/)

pyjs is a modern [pybind11](https://github.com/pybind/pybind11) + emscripten
[embind](https://emscripten.org/docs/porting/connecting_cpp_and_javascript/embind.html)
based Python <-> JavaScript foreign function interface (FFI) for wasm/emscripten
compiled Python. The API is loosely based on the FFI of
[pyodide](https://pyodide.org/en/stable/usage/type-conversions.html).

* Python 3.14, emscripten 6, `wasm32` and `wasm64`
* runs in the browser main thread and in web workers
* asyncio support: `await` JavaScript promises from Python and Python
  coroutines from JavaScript
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
pyjs.eval("print('Hello, World!')")

// eval a python expression and get the result
const py_list = pyjs.eval("[i for i in range(10)]")

// access
console.log(py_list.get(0)) // same as py_list[0] on the python side
```

## Development

Building, testing, benchmarking and building the docs all go through
`build_local.sh` (only [micromamba](https://mamba.readthedocs.io) is needed),
the CI uses the same script:

```bash
./build_local.sh build wasm32           # build pyjs
./build_local.sh test wasm64            # build + run the tests in the browser
BROWSERS="chromium firefox webkit" ./build_local.sh test wasm32
./build_local.sh bench wasm32           # FFI / asyncio benchmarks
./build_local.sh docs                   # sphinx docs + jupyterlite
./build_local.sh npm                    # npm package
```

See [development](https://emscripten-forge.github.io/pyjs/development.html)
for details.
