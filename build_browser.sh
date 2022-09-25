#!/bin/bash
set -e


cd build



# let cmake know where the env is
export PREFIX=$MAMBA_ROOT_PREFIX/envs/pyjs-browser
export CMAKE_PREFIX_PATH=$PREFIX
export CMAKE_SYSTEM_PREFIX_PATH=$PREFIX

# build pyjs
emcmake cmake \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_FIND_ROOT_PATH_MODE_PACKAGE=ON \
    -DBUILD_RUNTIME_BROWSER=ON \
    -DBUILD_RUNTIME_NODE=OFF \
    -DCMAKE_INSTALL_PREFIX=$PREFIX \
    ..


make -j12 


# make install
# cp ../examples/repl.html .

# python -m http.server
