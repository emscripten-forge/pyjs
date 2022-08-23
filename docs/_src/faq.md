# FAQ:

## What is pyjs?
`pyjs` is C++ library, compiled to wasm, which allows to run Python code in the browser or in node.

## Why not use the plain python executable compiled to wasm?
While this would be possible, it would be a very limited API.
`pyjs` not only allows you to call Python from JavaScript, but also calling JavaScript from Python.


## Why not use pyodide
* The code of `pyodide` is strongly coupled to pyodides packaging system while `pyjs` focus on `emscripten-forge`.
* `pyodide` uses raw Pthon-C-API  while `pyjs` uses high level `pybind11`
* `pyjs` uses `embind` instead of emscriptens more raw apis
