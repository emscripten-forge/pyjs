# Embedding pyjs in C++
Not only can `pyjs` be used as a standalone Python interpreter, but it can also be embedded in a C++ program. This allows you to run Python code in a C++ program.
Pyjs is compiled as a static library that can be linked to a C++ program (when compiled with emscripten).


To include `pyjs` in a C++ program, the following code is needed:

```C++

#include <emscripten/bind.h>
#include <pybind11/embed.h>

#include <pyjs/export_pyjs_module.hpp>
#include <pyjs/export_js_module.hpp>

// export the python core module of pyjs
PYBIND11_EMBEDDED_MODULE(pyjs_core, m) {
    pyjs::export_pyjs_module(m);
}

// export the javascript  module of pyjs
EMSCRIPTEN_BINDINGS(my_module) {
    pyjs::export_js_module();
}

```

In the CMakelists.txt file, the following lines are needed to link the `pyjs` library:

```CMake
find_package(pyjs ${pyjs_REQUIRED_VERSION} REQUIRED)

target_link_libraries(my_target PRIVATE pyjs)

target_link_options(my_target
    PUBLIC "SHELL: -s LZ4=1"
    PUBLIC "SHELL: --post-js  ${pyjs_PRO_JS_PATH}"
    PUBLIC "SHELL: --pre-js   ${pyjs_PRE_JS_PATH}"
    PUBLIC "SHELL: -s MAIN_MODULE=1"
    PUBLIC "SHELL: -s WASM_BIGINT"
    PUBLIC "-s DEFAULT_LIBRARY_FUNCS_TO_INCLUDE=\"['\$Browser', '\$ERRNO_CODES']\" "
)
```
As described in the [deployment](../installation) section, the needs to be packed.
See the [pack the environment](../installation/#pack-the-environment)-section for instructions on to pack the environment with [`empack`](https://github.com/emscripten-forge/empack).

