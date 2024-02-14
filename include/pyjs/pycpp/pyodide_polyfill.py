

def install_pyodide_polyfill():
    # Expose a small pyodide polyfill
    def _pyodide__getattr__(name: str) -> Any:
        if name == "to_js":
            from pyjs import to_js
            return to_js

        raise AttributeError(
            "This is not the real Pyodide. We are providing a small Pyodide polyfill for conveniance."
            "If you are missing an important Pyodide feature, please open an issue in https://github.com/emscripten-forge/pyjs/issues"
        )

    pyodide = sys.modules["pyodide"] = types.ModuleType("pyodide")
    pyodide.ffi = sys.modules["pyodide.ffi"] = types.ModuleType("ffi")
    pyodide.ffi.JsException = JsException
    pyodide.ffi.JsArray = object
    pyodide.ffi.JsProxy = object
    pyodide.__getattr__ = _pyodide__getattr__
    pyodide.ffi.__getattr__ = _pyodide__getattr__



install_pyodide_polyfill()
del install_pyodide_polyfill