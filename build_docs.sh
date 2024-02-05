#!/bin/bash
set -e

# dir of this script
THIS_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
WASM_ENV_NAME=pyjs-wasm-dev
WASM_ENV_PREFIX=$MAMBA_ROOT_PREFIX/envs/$WASM_ENV_NAME
EMSDK_DIR=$THIS_DIR/emsdk_install
EMSDK_VERSION="3.1.45"




if [ ! -d "$EMSDK_DIR" ]; then
    echo "Creating emsdk dir $EMSDK_DIR"
    $THIS_DIR/emsdk/setup_emsdk.sh $EMSDK_VERSION $EMSDK_DIR
else
    echo "Emsdk dir $EMSDK_DIR already exists"
fi

PYJS_PROBE_FILE=$WASM_ENV_PREFIX/lib_js/pyjs/pyjs_runtime_browser.js

if [ ! -d "$WASM_ENV_PREFIX" ]; then
    echo "Creating wasm env $WASM_ENV_NAME"
    micromamba create -n $WASM_ENV_NAME \
            --platform=emscripten-wasm32 \
            -c https://repo.mamba.pm/emscripten-forge \
            -c https://repo.mamba.pm/conda-forge \
            --yes \
            python pybind11 nlohmann_json pybind11_json numpy \
            bzip2 sqlite zlib libffi exceptiongroup \
            xeus xeus-lite xeus-python-shell xeus-javascript xtl 

else
    echo "Wasm env $WASM_ENV_NAME already exists"
fi




if [ ! -f "$PYJS_PROBE_FILE" ]; then
    echo "Building pyjs"

    cd $THIS_DIR
    source $EMSDK_DIR/emsdk_env.sh

    mkdir -p build
    cd build

    export PREFIX=$WASM_ENV_PREFIX
    export CMAKE_PREFIX_PATH=$PREFIX
    export CMAKE_SYSTEM_PREFIX_PATH=$PREFIX

    emcmake cmake \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_FIND_ROOT_PATH_MODE_PACKAGE=ON \
    -DBUILD_RUNTIME_BROWSER=ON \
    -DBUILD_RUNTIME_NODE=OFF \
    -DCMAKE_INSTALL_PREFIX=$PREFIX \
    ..

    emmake make -j2
    emmake make install

else 
    echo "Skipping build pyjs"
fi

# if there is no xeus-python dir, clone it
if [ ! -d "$THIS_DIR/xeus-python" ]; then
    cd $THIS_DIR
    git clone https://github.com/jupyter-xeus/xeus-python/
else
    echo "xeus-python dir already exists"
fi


PYJS_PROBE_FILE=$WASM_ENV_PREFIX/share/jupyter/kernels/xpython/kernel.json
if [ ! -f "$PYJS_PROBE_FILE" ]; then
    echo "Building xeus-python"

    cd $THIS_DIR
    source $EMSDK_DIR/emsdk_env.sh


    cd xeus-python

    export PREFIX=$WASM_ENV_PREFIX
    export CMAKE_PREFIX_PATH=$PREFIX
    export CMAKE_SYSTEM_PREFIX_PATH=$PREFIX          


    # remove the fake python
    rm -rf $PREFIX/bin/python*
    rm -rf $PREFIX/bin/pip*
    mkdir -p build_wasm
    cd build_wasm


    emcmake cmake .. \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_FIND_ROOT_PATH_MODE_PACKAGE=ON \
        -DCMAKE_INSTALL_PREFIX=$PREFIX \
        -DXPYT_EMSCRIPTEN_WASM_BUILD=ON\


    emmake make -j8 install

    rm -rf $WASM_ENV_PREFIX/share/jupyter/kernels/xpython-raw

else
    echo "Skipping build xeus-python"
fi



if true ; then
    echo "Building docs"

    cd $THIS_DIR/docs

    WASM_ENV_PREFIX=$WASM_ENV_PREFIX LITE=1 make html

    # post-build
    
    WASM_ENV_PREFIX=$WASM_ENV_PREFIX python ./post_build.py

fi