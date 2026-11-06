# Try pyjs

The REPL below runs Python with pyjs in your browser
([xeus-python](https://github.com/jupyter-xeus/xeus-python) kernel in
[JupyterLite](https://jupyterlite.readthedocs.io)).
For a full fledged example, open the
<a href="lite/lab/index.html?path=py_api_tour.ipynb">tour of the Python API</a>
in JupyterLite.

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

## From JavaScript

pyjs can also be used from JavaScript: the
<a href="lite/lab/index.html?path=js_api_tour.ipynb">tour of the JavaScript API</a>
runs in the JavaScript kernel of
[jupyterlite-javascript-kernel](https://github.com/jupyterlite/javascript-kernel)
(the notebook uses the IFrame runtime, it also works with the Web Worker runtime).
It loads the pyjs runtime (`pyjs_runtime_browser.js` / `.wasm`) and a packed
environment, deployed next to the JupyterLite in `pyjs-runtime/`.

