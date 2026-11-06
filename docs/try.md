# Try pyjs

The REPL below runs Python with pyjs in your browser
([xeus-python](https://github.com/jupyter-xeus/xeus-python) kernel in
[JupyterLite](https://jupyterlite.readthedocs.io)).
For a full fledged example, open the
<a href="lite/lab/index.html?path=py_api_tour.ipynb">tour of the Python API</a>
in JupyterLite, or see how synchronous Python code can
<a href="lite/lab/index.html?path=run_sync.ipynb">wait for JavaScript promises</a>
(`pyjs.run_sync`).

```{replite}
:kernel: xpython
:height: 600px
:prompt: Try pyjs

import pyjs

# call JavaScript from Python
pyjs.js.console.log("Hello from Python!")

add = pyjs.js.Function("a", "b", "return a + b")
add(1, 2)
```

## 64 bit (wasm64)

All of this also exists as a 64 bit build (wasm64, can use more than 4 GB of
memory, needs a browser with WebAssembly memory64 support):
<a href="lite64/lab/index.html">JupyterLite with the wasm64 Python kernel</a>,
e.g. the <a href="lite64/lab/index.html?path=py_api_tour.ipynb">tour of the Python API</a>.

## From JavaScript

pyjs can also be used from JavaScript: the
<a href="lite/lab/index.html?path=js_api_tour.ipynb">tour of the JavaScript API</a>
runs in the JavaScript kernel of
[jupyterlite-javascript-kernel](https://github.com/jupyterlite/javascript-kernel)
(the notebook uses the IFrame runtime, it also works with the Web Worker runtime).
It loads the pyjs runtime (`pyjs_runtime_browser.js` / `.wasm`) and a packed
environment, deployed next to the JupyterLite in `pyjs-runtime/wasm32/` and
`pyjs-runtime/wasm64/` (the wasm64 one when the browser supports memory64).

