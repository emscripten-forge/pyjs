# pyjs
[![CI](https://github.com/DerThorsten/pyjs/actions/workflows/main.yml/badge.svg)](https://github.com/DerThorsten/pyjs/actions/workflows/main.yml)

## What is pyjs

pyjs is  modern [pybind11](https://github.com/pybind/pybind11) + emscripten [Embind](https://emscripten.org/docs/porting/connecting_cpp_and_javascript/embind.html) based
Python <-> JavaScript foreign function interface (FFI) for wasm/emscripten compiled Python.

The API is loosly based on the  FFI of [pyodide](https://pyodide.org/en/stable/usage/type-conversions.html).
The webloop impl *is pyodides webloop impl


## Building the REPL example

To build a simple "repl"-example, run the following commands:

First, we set up a simple "prefix" that contains the dependencies compiled to webassembly (including Python, pybind11, numpy ...)

```sh
# Install micromamba on Linux and create a base environment
curl micro.mamba.pm/install.sh | bash
source ~/.bashrc

micromamba activate
micromamba install empack cmake emsdk

# install and activate emsdk
emsdk install 3.1.2
emsdk activate 3.1.2
source $CONDA_EMSDK_DIR/emsdk_env.sh
```


```sh
# install micromamba on Linux or macOS (note empack only works reliably on Linux)

rm -rf $MAMBA_ROOT_PREFIX/envs/pyjs-build-wasm

# install wasm env
micromamba create -n pyjs-build-wasm \
    --platform=emscripten-32 \
    -c https://repo.mamba.pm/emscripten-forge \
    -c conda-forge \
    --yes \
    python pybind11 nlohmann_json pybind11_json numpy pytest bzip2 sqlite zlib libffi
```

Then we create a build directory:

```sh
# create build/work dir
mkdir -p build_repl
cd build_repl
```
