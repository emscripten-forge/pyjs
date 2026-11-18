# C++ / static library (advanced)

```{note}
Most users want the [npm package](npm.md): it contains the runtime, Python and
its standard library, and installs further packages at runtime. This page is
for projects that deploy the pyjs runtime themselves (the build output of the
`pyjs-dev` conda package) or embed pyjs into their own WebAssembly program, as
e.g. [xeus-python](https://github.com/jupyter-xeus/xeus-python) does.
```

## Deploying the prebuilt runtime

### Prerequisites

Before we start, let's introduce a few concepts and tools that are used in the pyjs workflow.
#### Emscripten-forge

[Emscripten-forge](https://github.com/emscripten-forge/recipes) is similar to [conda-forge](https://conda-forge.org/) and provides packages compiled to webassembly using emscripten.

#### Empack
https://github.com/emscripten-forge/empack is a tool to "pack" conda environments into a set of files that can be consumed by pyjs.


### Steps

So we assume there is a directory called `/path/to/deploy` where we will
put all files which need to be served to the user.

#### Define a conda environment
Pyjs has a conda-like workflow. This means the first step 
is to create an environment with the `pyjs` package installed
and all packages required for the project.

```yaml
name: my-pyjs-env
channels:
  - https://repo.prefix.dev/emscripten-forge/6x
  - conda-forge
dependencies:
  - pyjs-dev
  - numpy
```

The name of the environment can be chosen by the user.
The `channels` section specifies the conda channels to use.
The emscripten-forge channel (`https://repo.prefix.dev/emscripten-forge/6x`)
is mandatory, it provides `pyjs` and all other packages compiled to WebAssembly.
The `conda-forge` channel is used for `noarch` (pure Python) packages.
`pyjs-dev` contains the pyjs Python module (`pyjs`) and the pyjs runtime
(`libpyjs-static`, with `lib_js/pyjs/pyjs_runtime_browser.{js,wasm}`).

#### Create the environment
Assuming the yaml file above is called `environment.yml` and is in the current directory, the  environment can be created using `micromamba`:

```Bash
micromamba create -f environment.yml \
    --platform emscripten-wasm32 --prefix /path/to/env
```

#### Copy pyjs
Copy the pyjs binary from the environment to the deploy directory.
This should move pyjs_runtime_browser.js and pyjs_runtime_browser.wasm to the deployment directory.

```Bash
cp /path/to/env/lib_js/pyjs/* /path/to/deploy
```



#### Pack the environment

After the environment is defined, the next step is to pack the environment using `empack`.

```Bash
empack pack env --env-prefix /path/to/env --outdir /path/to/deploy
```
This will create a tarball for each package in the environment and a `empack_env_meta.json` file that describes the environment.


#### The html/JavaScript code

The last step is to create a html file that loads the pyjs runtime and the
packed environment. pyjs itself does not fill the file system: the page
writes the environment into it (here with the runtime's extractor,
`_extract_archive`, which unpacks tar / zip archives compressed with gzip,
bzip2 or zstd), loads shared libraries if it runs in the main thread, and then
starts Python with `startPython()`.

```html
<!DOCTYPE html>
<html>
  <head>
    <title>Pyjs Example</title>
    <script src="pyjs_runtime_browser.js"></script>
    <script>
      async function runPyjs() {
        const pyjs = await createModule({
          // location of the wasm file on the server
          locateFile: (file) => `./${file}`,
        });

        // fill the file system: the pre-relocated tarballs of the packed env
        const meta = await (await fetch("./empack_env_meta.json")).json();
        const sharedLibs = [];
        for (const pkg of [...meta.packages, ...(meta.mounts ?? [])]) {
          const bytes = new Uint8Array(await (await fetch(`./${pkg.filename}`)).arrayBuffer());
          sharedLibs.push(...pyjs._extract_archive(bytes, "/", {}).sharedLibs);
        }

        pyjs.startPython();

        // main thread: load the shared libraries asynchronously now (a large
        // library cannot be compiled synchronously at `import` time there);
        // in a worker this is not needed. After startPython: loading an
        // extension module runs its static initializers (python C API)
        for (const path of sharedLibs) {
          const stack = pyjs.stackSave();
          const pid = pyjs._emscripten_dlopen_promise(pyjs.stringToUTF8OnStack(path), 2 /* RTLD_NOW */);
          pyjs.stackRestore(stack);
          const promise = pyjs.getPromise(pid);
          pyjs.promiseMap.free(pid);
          await promise;
        }

        pyjs.eval("print('hello world')");
      }
      runPyjs();
    </script>
  </head>
  <body>
    <h1>Pyjs Example</h1>
  </body>
</html>
```

`startPython()` is synchronous and starts the interpreter once (later calls
do nothing): it needs the
standard library at `/lib/pythonX.Y` (an error otherwise) and sets up
`exec`, `eval`, `exec_eval`, `async_exec_eval`, `to_js`, ...;
`startPython({env: {NAME: "value"}})` sets extra environment variables.

## Embedding pyjs in a C++ program

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

# the essential options of pyjs' own runtime (see its CMakeLists.txt)
target_link_options(my_target
    PUBLIC "SHELL: --pre-js ${pyjs_PRE_JS_PATH}"
    PUBLIC "SHELL: --post-js ${pyjs_POST_JS_PATH}"
    PUBLIC "SHELL: -s MAIN_MODULE=1"
    PUBLIC "SHELL: -s MODULARIZE=1"
    PUBLIC "SHELL: -s EXPORT_NAME=createModule"
    PUBLIC "SHELL: -s FORCE_FILESYSTEM"
    PUBLIC "SHELL: -s ALLOW_MEMORY_GROWTH=1"
    PUBLIC "SHELL: -fwasm-exceptions"
    PUBLIC "SHELL: -s SUPPORT_LONGJMP"
    PUBLIC "SHELL: -lembind"
)
```
Such a program fills the file system itself (the archive extractor is part of
pyjs' own runtime only, not of the static library), e.g. with
[mambajs](https://github.com/emscripten-forge/mambajs) or `FS.writeFile`, and
then calls `Module.startPython()`. Shared libraries are not preloaded by
pyjs: in the main thread, load them after `startPython()` and before importing
them (see above).

```{note}
pyjs 5 removed the classic initialization API
(`bootstrap_from_empack_packed_environment`, `init_phase_1` / `init_phase_2`,
`_untar`, `_install_conda_file`): fill the file system, then `startPython()`.
```
