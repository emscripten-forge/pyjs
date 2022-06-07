# pyjs
[![CI](https://github.com/DerThorsten/pyjs/actions/workflows/main.yml/badge.svg)](https://github.com/DerThorsten/pyjs/actions/workflows/main.yml)

A modern [pybind11](https://github.com/pybind/pybind11) + emscripten [Embind](https://emscripten.org/docs/porting/connecting_cpp_and_javascript/embind.html) based
Python <-> JavaScript foreign function interface (FFI) for wasm/emscripten compiled Python.

The API is loosly based on the  FFI of [pyodide](https://pyodide.org/en/stable/usage/type-conversions.html).
The webloop impl *is* pyodides webloop impl
