#!/bin/bash
set -e

# install wasm env
rm -rf $MAMBA_ROOT_PREFIX/envs/pyjs-build-wasm
micromamba create -n pyjs-build-wasm \
    --platform=emscripten-32 \
    -c https://repo.mamba.pm/emscripten-forge \
    -c https://repo.mamba.pm/conda-forge \
    --yes \
    python pybind11 nlohmann_json pybind11_json numpy pytest bzip2 sqlite zlib libffi


# create build/work dir
mkdir -p build_repl
cd build_repl


# pack the environment in a js/data file
empack pack python core $MAMBA_ROOT_PREFIX/envs/pyjs-build-wasm --version=3.10

# let cmake know where the env is
export PREFIX=$MAMBA_ROOT_PREFIX/envs/pyjs-build-wasm
export CMAKE_PREFIX_PATH=$PREFIX
export CMAKE_SYSTEM_PREFIX_PATH=$PREFIX

# build pyjs
emcmake cmake \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_FIND_ROOT_PATH_MODE_PACKAGE=ON \
    -DBUILD_RUNNER=ON \
    ..

cp ../examples/repl.html .

python -m http.server
