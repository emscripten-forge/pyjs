# Embedding pyjs in your own program

The smallest program that embeds pyjs: it links `libpyjs` and libpython into
its own emscripten main module, puts the python standard library into its
file system with emscripten's file packager, starts python from JavaScript
and prints `hello world`, in node.

```bash
pixi run run wasm32        # or wasm64: build + run + check the output
```

| file | |
|---|---|
| `pixi.toml` | the environments: the native tools (emscripten, cmake, node) and the emscripten environment the program is built against (python, its static libraries) |
| `CMakeLists.txt` | the program: `find_package(pyjs)`, linked with libpython; the file system (`--preload-file`) |
| `main.cpp` | empty: python is started from JavaScript |
| `run.js` | `createModule()`, `Module.startPython()`, `Module.runPython(...)` |

## Where pyjs comes from

**Normally pyjs comes from emscripten-forge**, like python itself: the
package `pyjs-dev` in the host environment brings `libpyjs.a`, its cmake
config (`lib/cmake/pyjs/pyjsConfig.cmake`), the runtime js / wasm (that is
`libpyjs-static`) and the python module `pyjs` (the package `pyjs`). A real
embedder adds it to its host dependencies (in this example's `pixi.toml` it is
there, commented out):

```toml
[feature.host.dependencies]
python = "3.14.*"
libpython-static = "*"
pyjs-dev = "*"
```

and `find_package(pyjs)` finds it there; the python module is in the host
environment's `site-packages`, i.e. in what the file packager packs. The
lines to change for that are marked "outside of the pyjs repository" in
`pixi.toml` and `CMakeLists.txt`.

This example lives in the pyjs repository and tests the pyjs of the same
commit (the CI runs it). So it takes pyjs from there instead: `libpyjs` from
the build tree (`build_root/build_<arch>`, `pixi run build <arch>` in the
repository root) and the python module from `module/pyjs`. Those are the only
two places where it differs from a real embedder (see `CMakeLists.txt`).

## What pyjs requires

- **a main module** (`-sMAIN_MODULE=1`): python extension modules are side
  modules, and pyjs relies on the main module keeping all of libpyjs and of
  emscripten's runtime JavaScript
- **the file system** filled before `Module.startPython()`: the standard
  library at `/lib/pythonX.Y`, the python package `pyjs` in its
  `site-packages`. How is up to the program; here the file packager does it
  at build time (other ways: `FS.writeFile`, an archive, mambajs, ...)
