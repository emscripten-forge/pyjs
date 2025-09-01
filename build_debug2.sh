#!/bin/bash
set -e

# dir of this script
THIS_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
PREFIX_DIR=$THIS_DIR/wasm_prefix
EMSDK_DIR=$THIS_DIR/emsdk_install
EMSDK_VERSION="3.1.58"

if [ ! -d "$EMSDK_DIR" ]; then
    echo "Creating emsdk dir $EMSDK_DIR"
    $THIS_DIR/emsdk/setup_emsdk.sh $EMSDK_VERSION $EMSDK_DIR
else
    echo "Emsdk dir $EMSDK_DIR already exists"
fi


if true; then
    rm -rf $PREFIX_DIR
    echo "Creating wasm env at $PREFIX_DIR"
    $MAMBA_EXE create -p $PREFIX_DIR \
            --platform=emscripten-wasm32 \
            -c https://repo.mamba.pm/emscripten-forge \
            -c https://repo.mamba.pm/conda-forge \
            --yes \
            python pybind11 "emscripten-abi=3.1.58"\
            bzip2 sqlite zlib libffi pytest
fi
   
cd $THIS_DIR
source $EMSDK_DIR/emsdk_env.sh


mkdir -p build
cd build

export PREFIX=$PREFIX_DIR
export CMAKE_PREFIX_PATH=$PREFIX
export CMAKE_SYSTEM_PREFIX_PATH=$PREFIX

emcmake cmake \
-DCMAKE_BUILD_TYPE=Release \
-DCMAKE_FIND_ROOT_PATH_MODE_PACKAGE=ON \
-DBUILD_RUNTIME_BROWSER=ON \
-DBUILD_RUNTIME_NODE=OFF \
-DCMAKE_INSTALL_PREFIX=$PREFIX \
..

emmake make -j8
emmake make install
