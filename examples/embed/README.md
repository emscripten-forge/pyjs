# Embedding pyjs in a C++ program

A small C++ program with python and pyjs in it, python code run with
pybind11, using numpy (shared libraries) and JavaScript. Everything is set up
from C++, the program needs no JavaScript of its own:

```cpp
pyjs_initialize("/python");           // python (prefix /python) with pyjs in it
pybind11::exec(R"(
import numpy as np, pyjs
a = np.arange(1, 5, dtype=np.float64)
norm = float(np.linalg.norm(a))                # numpy (openblas)
js_norm = pyjs.js.Math.sqrt(float(a @ a))      # JavaScript
)");
```

prints `numpy 2.5.5: |[1. 2. 3. 4.]| = 5.477226, JavaScript's Math.sqrt:
5.477226`. Python's prefix is `/python` on purpose (any directory works, the
default is `/`), and numpy's extension modules are shared libraries (side
modules) loaded at `import numpy`, with `libopenblas.so` from
`/python/lib`: the CI runs this, so both stay tested.

pybind11 works in an interpreter it did not start (as in every pybind11
extension module); only it must not finalize it (no
`pybind11::scoped_interpreter`).

The python standard library is put into the program's file system with
emscripten's file packager (`--embed-file`). Run in node:

```bash
pixi run run wasm32        # or wasm64: build + run
```

| file | |
|---|---|
| `pixi.toml` | the environments: the native tools (emscripten, cmake, node) and the emscripten environment the program is built against (python, pybind11, numpy, the static libraries) |
| `CMakeLists.txt` | the program: `find_package(pyjs)`, linked with libpython; the file system under `/python` (`--embed-file`: the standard library, site-packages, `libopenblas.so`) |
| `main.cpp` | starts python with pyjs, runs python code that uses numpy and calls JavaScript |

## The C API of pyjs (`pyjs/pyjs.h`)

| | |
|---|---|
| `pyjs_initialize(python_home)` | starts python with pyjs in it. `python_home`: python's prefix in the file system, any directory (`NULL`: `PYTHONHOME` if set, else `/`); defaults for `PYTHONPATH`, `LANG`, `LD_LIBRARY_PATH` (`<python_home>/lib`: where the dynamic linker finds e.g. `libopenblas.so`) unless the program set them. What `Module.startPython()` does from JavaScript |
| `pyjs_init()` | for a program that starts python itself (its own `PyConfig`, `pybind11::initialize_interpreter(...)`, ...): before python is initialized, registers `pyjs_core` (the core of pyjs, compiled into the program) as builtin module, sets up pyjs' JavaScript side |
| `pyjs_bind()` | ... and after python is initialized: imports `pyjs`, creates its JavaScript API (`Module.runPython`, ... for JavaScript that wants to call python) and keeps the runtime alive |

## Where pyjs comes from

**Normally pyjs comes from emscripten-forge**, like python itself: the
package `pyjs-dev` in the host environment brings `libpyjs.a`, its header and
cmake config (`lib/cmake/pyjs/pyjsConfig.cmake`), the runtime js / wasm (that
is `libpyjs-static`) and the python module `pyjs` (the package `pyjs`). A real
embedder adds it to its host dependencies (in this example's `pixi.toml` it is
there, commented out):

```toml
[feature.host.dependencies]
python = "3.14.*"
libpython-static = "*"
pybind11 = "*"
pyjs-dev = "*"
```

and `find_package(pyjs)` finds it there; the python module is in the host
environment's `site-packages`, i.e. in what the file packager packs. The
lines to change for that are marked "outside of the pyjs repository" in
`pixi.toml` and `CMakeLists.txt`.

This example lives in the pyjs repository and tests the pyjs of the same
commit (the CI runs it). So it takes pyjs from there instead: `libpyjs` from
the build tree (`build_root/build_<arch>`, `pixi run build <arch>` in the
repository root) and the python module from `module/pyjs`.

## What pyjs requires

- **a main module** (`-sMAIN_MODULE=1`): python extension modules are side
  modules, and pyjs relies on the main module keeping all of libpyjs and of
  emscripten's runtime JavaScript
- **the file system** filled before python starts: the standard library at
  `<prefix>/lib/pythonX.Y`, the python package `pyjs` in its `site-packages`,
  the packages' shared libraries in `<prefix>/lib`. How is up to the program;
  here the file packager does it at build time (other ways: `FS.writeFile`,
  an archive, mambajs, ...). Loading shared libraries synchronously at
  `import` works in node and in web workers; a page's main thread must load
  large ones asynchronously first (`docs/cpp.md`)
- **python is not finalized** when `main` returns (no
  `pybind11::scoped_interpreter`): JavaScript events (asyncio, callbacks)
  call into python later
