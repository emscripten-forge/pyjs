# pyjs

pyjs is a Python ↔ JavaScript FFI for WebAssembly, built with
[pybind11](https://github.com/pybind/pybind11) and emscripten's
[embind](https://emscripten.org/docs/porting/connecting_cpp_and_javascript/embind.html).
It lets you run Python in the browser (main thread or web worker) and use
JavaScript from Python, and Python from JavaScript.

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

## Try it out

Use the [Python REPL](try.md) in these docs, the
<a href="lite/lab/index.html?path=js_api_tour.ipynb">JavaScript API tour</a>, or the full
<a href="lite/lab/index.html">JupyterLite deployment</a>.

```{toctree}
:maxdepth: 2
:caption: User guide

try
installation
embed
```

```{toctree}
:maxdepth: 2
:caption: API reference

JavaScript_API
api/python/pyjs/index
api/python/pyjs_core/index
```

```{toctree}
:maxdepth: 2
:caption: Internals

design
development
```
