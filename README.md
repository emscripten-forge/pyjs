# pyjs
[![CI](https://github.com/emscripten-forge/pyjs/actions/workflows/main.yml/badge.svg)](https://github.com/emscripten-forge/pyjs/actions/workflows/main.yml)
[![CI](https://img.shields.io/badge/pyjs-docs-yellow)](https://emscripten-forge.github.io/pyjs/)



## What is pyjs

pyjs is  modern [pybind11](https://github.com/pybind/pybind11) + emscripten [Embind](https://emscripten.org/docs/porting/connecting_cpp_and_javascript/embind.html) based
Python <-> JavaScript foreign function interface (FFI) for wasm/emscripten compiled Python.

The API is loosly based on the  FFI of [pyodide](https://pyodide.org/en/stable/usage/type-conversions.html).


## Quickstart

Access Javascript from Python:

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

Access Python from Javascript:

```JavaScript
// hello world
pyjs.eval("print('Hello, World!')")

// eval a python expression and get the result
const py_list = pyjs.eval("[i for i in range(10)]")

/// access 
console.log(py_list.get(0)) // same as py_list[0] on the python side
```

## Full Documentation
See the [documentation](https://emscripten-forge.github.io/pyjs/) for a full documentation.

## Try it out
To try it out, you can use the [playground](https://emscripten-forge.github.io/pyjs/lite/).