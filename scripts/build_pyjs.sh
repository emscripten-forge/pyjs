#!/bin/bash

set -eux

# Check if PREFIX argument is provided
if [ $# -eq 0 ]; then
    echo "Usage: $0 <PREFIX>"
    echo ""
    echo "Build pyjs with the specified installation prefix."
    echo ""
    echo "Arguments:"
    echo "  PREFIX    Installation prefix path"
    echo ""
    exit 1
fi

PREFIX=$1

mkdir build
pushd build

export CMAKE_PREFIX_PATH=$PREFIX
export CMAKE_SYSTEM_PREFIX_PATH=$PREFIX

emcmake cmake \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_FIND_ROOT_PATH_MODE_PACKAGE=ON \
    -DBUILD_RUNTIME_BROWSER=ON \
    -DBUILD_RUNTIME_NODE=OFF \
    -DCMAKE_INSTALL_PREFIX=$PREFIX \
    ..

make -j2
make install

popd