# pyjs

pyjs is a Python ↔ JavaScript FFI for WebAssembly (CPython compiled with
emscripten, wasm32 and wasm64). It lets you run Python in the browser (main
thread or web worker) and use JavaScript from Python, and Python from
JavaScript. Its API follows [PEP 818](https://peps.python.org/pep-0818/) and
pyodide, so code written for pyodide runs unchanged.

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

## Try it out

The <a href="playground/index.html">playground</a> runs Python with pyjs in
your browser, with a canvas to draw on from Python.

## Using pyjs

- [npm package](npm.md): the recommended way, for apps with or without a bundler
- [CDN](cdn.md): one `import` in a plain html page
- [C++ / static library](cpp.md) (advanced): deploying the raw runtime, or
  embedding pyjs into your own WebAssembly program

## Further references

- [xeus-python](https://github.com/jupyter-xeus/xeus-python): the Jupyter
  kernel built on pyjs, try it in
  [JupyterLite](https://jupyterlite.github.io/demo/lab/index.html)
- [emscripten-forge](https://github.com/emscripten-forge/recipes): the conda
  packages compiled to WebAssembly (python, numpy, scipy, ...) that pyjs
  installs
- [mambajs](https://github.com/emscripten-forge/mambajs): the package manager
  the npm package uses at runtime

```{toctree}
:hidden:

usage
reference
internals
```
