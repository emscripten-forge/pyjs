#!/bin/bash
set -e


BUILD_DIR=build_tests
# create build/work dir
mkdir -p $BUILD_DIR
cd $BUILD_DIR

ENV_NAME=pyjs-browser


if false; then
# install wasm env
# rm -rf $MAMBA_ROOT_PREFIX/envs/pyjs-node-testsar
micromamba create -n pyjs-browser \
    --platform=emscripten-32 \
    -c https://repo.mamba.pm/emscripten-forge \
    -c https://repo.mamba.pm/conda-forge \
    --yes \
    python pybind11 nlohmann_json pybind11_json numpy pytest bzip2 sqlite zlib libffi xeus xeus-lite xtl xeus

fi 


# let cmake know where the env is
export PREFIX=$MAMBA_ROOT_PREFIX/envs/$ENV_NAME
export CMAKE_PREFIX_PATH=$PREFIX
export CMAKE_SYSTEM_PREFIX_PATH=$PREFIX

# build pyjs
emcmake cmake \
    -DCMAKE_BUILD_TYPE=MinSizeRel \
    -DCMAKE_FIND_ROOT_PATH_MODE_PACKAGE=ON \
    -DBUILD_RUNTIME_BROWSER=ON \
    -DBUILD_RUNTIME_NODE=OFF \
    -DCMAKE_INSTALL_PREFIX=$PREFIX \
    ..

emmake make -j12 install


pyjs_code_runner run script \
        browser-main \
        --conda-env     $PREFIX  \
        --mount         $(pwd)/../tests:tests \
        --script        main.py \
        --work-dir      /tests \
        --pyjs-dir      $(pwd)/../$BUILD_DIR \
        --headless \
        --async-main