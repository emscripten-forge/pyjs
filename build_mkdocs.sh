#!/bin/bash
set -e

# dir of this script
THIS_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
WASM_ENV_NAME=pyjs-wasm-dev
WASM_ENV_PREFIX=$MAMBA_ROOT_PREFIX/envs/$WASM_ENV_NAME
EMSDK_DIR=$WASM_ENV_PREFIX/opt/emsdk
EMSDK_VERSION=$1
PYTHON_VERSION=$2


 

PYJS_PROBE_FILE=$WASM_ENV_PREFIX/lib_js/pyjs/pyjs_runtime_browser.js

if [ ! -d "$WASM_ENV_PREFIX" ]; then
    echo "Creating wasm env $WASM_ENV_NAME"
    micromamba create -n $WASM_ENV_NAME \
            --platform=emscripten-wasm32 \
            -c https://repo.mamba.pm/emscripten-forge \
            -c https://repo.mamba.pm/conda-forge \
            --yes \
            python==$PYTHON_VERSION emscripten-abi==$EMSDK_VERSION "pybind11<2.12.0" nlohmann_json pybind11_json numpy \
            bzip2 sqlite zlib zstd libffi exceptiongroup \
            "xeus<4" "xeus-lite<2" xeus-python "xeus-javascript>=0.3.2" xtl "ipython=8.22.2=py311had7285e_1" "traitlets>=5.14.2"

else
    echo "Wasm env $WASM_ENV_NAME already exists"
fi




if true; then
    echo "Building pyjs"

    cd $THIS_DIR
  
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
    git clone -b pyjs_update https://github.com/DerThorsten/xeus-python/
else
    echo "xeus-python dir already exists"
fi



if true; then

    echo "Building xeus-python"

    cd $THIS_DIR
    # source $EMSDK_DIR/emsdk_env.sh


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
    if [ -d "$WASM_ENV_PREFIX/share/jupyter/kernels/xpython-raw" ]; then
        rm -rf $WASM_ENV_PREFIX/share/jupyter/kernels/xpython-raw
    fi

else
    echo "Skipping build xeus-python"
fi


if false; then
    echo "Building xeus-javascript"

    cd $THIS_DIR
    # source $EMSDK_DIR/emsdk_env.sh


    cd ~/src/xeus-javascript
    mkdir -p build_wasm
    cd build_wasm

    export PREFIX=$WASM_ENV_PREFIX
    export CMAKE_PREFIX_PATH=$PREFIX
    export CMAKE_SYSTEM_PREFIX_PATH=$PREFIX          


    emcmake cmake .. \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_FIND_ROOT_PATH_MODE_PACKAGE=ON \
        -DCMAKE_INSTALL_PREFIX=$PREFIX \
        -DXPYT_EMSCRIPTEN_WASM_BUILD=ON\
    
    emmake make -j8 install
else
    echo "Skipping build xeus-javascript"
fi



if true ; then

    rm -rf $THIS_DIR/docs_build
    mkdir -p $THIS_DIR/docs_build

    # convert *.py to *.ipynb using jupytext
    NOTEBOOK_OUTPUT_DIR=$THIS_DIR/docs_build/notebooks
    rm -rf $NOTEBOOK_OUTPUT_DIR
    mkdir -p $NOTEBOOK_OUTPUT_DIR

    for f in $THIS_DIR/examples/*.py; do
        #  get the filename without the extension and path
        filename=$(basename -- "$f")
        jupytext $f --to ipynb  --output $NOTEBOOK_OUTPUT_DIR/${filename%.*}.ipynb   --update-metadata '{"kernelspec": {"name": "xpython"}}' 
    done
    for f in $THIS_DIR/examples/*.js; do
        #  get the filename without the extension and path
        filename=$(basename -- "$f")
        jupytext $f --to ipynb  --output $NOTEBOOK_OUTPUT_DIR/${filename%.*}.ipynb  --update-metadata '{"kernelspec": {"name": "xjavascript"}}' 
    done



    # lite
    if true; then
        cd $THIS_DIR
        rm -rf docs_build/_output
        rm -rf docs_build/.jupyterlite.doit.db
        mkdir -p docs_build
        cd docs_build

        jupyter lite build \
                --contents=$NOTEBOOK_OUTPUT_DIR \
                --XeusAddon.prefix=$WASM_ENV_PREFIX \
                --XeusAddon.mounts=$THIS_DIR/module/pyjs:/lib/python3.11/site-packages/pyjs 
    fi
fi


# the docs itself
if true ; then

    export PREFIX=$MAMBA_ROOT_PREFIX/envs/pyjs-wasm
    echo "Building docs"

    cd $THIS_DIR
    mkdir -p docs_build/mkdocs
    export PYTHONPATH=$PYTHONPATH:$THIS_DIR/stubs
    export PYTHONPATH=$PYTHONPATH:$THIS_DIR/module
    mkdocs build  --site-dir=docs_build/mkdocs


fi

if true ; then
    # # copy lite _output to docs_build
    cp -r $THIS_DIR/docs_build/_output $THIS_DIR/docs_build/mkdocs/lite
    # copy pyjs binary to docs_build
    cp $WASM_ENV_PREFIX/lib_js/pyjs/* $THIS_DIR/docs_build/mkdocs/lite/xeus/bin/

fi