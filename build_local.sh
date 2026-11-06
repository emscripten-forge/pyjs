#!/bin/bash
# Local build of pyjs
#
# Usage: ./build_local.sh [wasm32|wasm64] [--fresh]
#
#   --fresh   delete and recreate the build + host environments
#
# Env overrides: EMSDK_VERSION, PYTHON_VERSION, NUM_JOBS, MAMBA_EXE,
#                SRC_DIR (pyjs source tree, default: this dir)
#
# Layout (all under build_root/):
#   build_prefix_<wasm>/   native env: python, cmake, make, emscripten
#                          compiler (emscripten_emscripten-<wasm>)
#   host_prefix_<wasm>/    emscripten env: libpython-static, pybind11, ...
#                          (pyjs is installed into this prefix)
#   build_<wasm>/          cmake build dir
set -euo pipefail

########################################
# arguments
########################################
WASM_TYPE="wasm32"
FRESH=0
for arg in "$@"; do
    case "$arg" in
        wasm32|wasm64) WASM_TYPE="$arg" ;;
        --fresh)       FRESH=1 ;;
        *)
            echo "Usage: $0 [wasm32|wasm64] [--fresh]"
            exit 1
            ;;
    esac
done

########################################
# configuration
########################################
THIS_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
SRC_DIR="${SRC_DIR:-$THIS_DIR}"

EMSDK_VERSION="${EMSDK_VERSION:-6.0.8}"
PYTHON_VERSION="${PYTHON_VERSION:-3.14}"
NUM_JOBS="${NUM_JOBS:-$(sysctl -n hw.ncpu 2>/dev/null || nproc)}"

PLATFORM="emscripten-$WASM_TYPE"
EMSCRIPTEN_FORGE_CHANNEL="https://repo.prefix.dev/emscripten-forge/6x"
CONDA_FORGE_CHANNEL="conda-forge"

BUILD_ROOT="$THIS_DIR/build_root"
BUILD_PREFIX="$BUILD_ROOT/build_prefix_$WASM_TYPE"
HOST_PREFIX="$BUILD_ROOT/host_prefix_$WASM_TYPE"
BUILD_DIR="$BUILD_ROOT/build_$WASM_TYPE"

########################################
# find micromamba / mamba
########################################
if [ -z "${MAMBA_EXE:-}" ]; then
    MAMBA_EXE="$(command -v micromamba || command -v mamba || true)"
fi
if [ -z "$MAMBA_EXE" ] || [ ! -x "$MAMBA_EXE" ]; then
    echo "Error: micromamba/mamba not found (set MAMBA_EXE)."
    exit 1
fi

if [ "$FRESH" = "1" ]; then
    echo "Removing existing environments and build dir"
    rm -rf "$BUILD_PREFIX" "$HOST_PREFIX" "$BUILD_DIR"
fi

########################################
# build environment (native)
########################################
if [ ! -d "$BUILD_PREFIX" ]; then
    echo "Creating build environment at $BUILD_PREFIX"
    # same as the recipe's build requirements:
    # compiler("c"), compiler("cxx"), cmake, make (+ python for merge_js.py)
    "$MAMBA_EXE" create -p "$BUILD_PREFIX" --yes \
        -c "$EMSCRIPTEN_FORGE_CHANNEL" \
        -c "$CONDA_FORGE_CHANNEL" \
        "python=$PYTHON_VERSION" \
        cmake \
        make \
        "emscripten_emscripten-$WASM_TYPE==$EMSDK_VERSION"
fi

########################################
# host environment (emscripten)
########################################
if [ ! -d "$HOST_PREFIX" ]; then
    echo "Creating host environment at $HOST_PREFIX ($PLATFORM)"
    "$MAMBA_EXE" create -p "$HOST_PREFIX" --yes \
        --platform "$PLATFORM" \
        -c "$EMSCRIPTEN_FORGE_CHANNEL" \
        -c "$CONDA_FORGE_CHANNEL" \
        "libpython-static=$PYTHON_VERSION" \
        pybind11 \
        "emscripten-abi==$EMSDK_VERSION"
fi

########################################
# activate build env
########################################
# PREFIX must point to the host env *before* activation:
# the emscripten activation script bakes it into CMAKE_ARGS / LDFLAGS.
export PREFIX="$HOST_PREFIX"
unset CONDA_FORGE_EMSCRIPTEN_ACTIVATED EMCC_CFLAGS EMCC_FLAGS LDFLAGS CFLAGS CXXFLAGS 2>/dev/null || true

# activation scripts are not nounset-safe
set +u
eval "$("$MAMBA_EXE" shell hook -s bash)"
micromamba activate "$BUILD_PREFIX"
set -u
# CMakeLists.txt uses $ENV{CONDA_PREFIX}/bin/python for merge_js.py
export CONDA_PREFIX="$BUILD_PREFIX"

if [ "$WASM_TYPE" = "wasm64" ]; then
    USE_WASM64=TRUE
else
    USE_WASM64=FALSE
fi

export CMAKE_PREFIX_PATH="$PREFIX"
export CMAKE_SYSTEM_PREFIX_PATH="$PREFIX"
export CC=emcc
export CXX=em++

########################################
# detect python version from host env
########################################
PY_VER=$(basename -- "$PREFIX"/include/python* | sed 's/^python//')
echo "Detected Python version: $PY_VER"
echo "emcc: $(command -v emcc)"

########################################
# configure / build / install
########################################
mkdir -p "$BUILD_DIR"
cd "$BUILD_DIR"

# CMAKE_ARGS (from emscripten-core activation) sets the emscripten toolchain
# file, CMAKE_PREFIX_PATH / CMAKE_FIND_ROOT_PATH and CMAKE_INSTALL_PREFIX.
# shellcheck disable=SC2086
emmake cmake ${CMAKE_ARGS:-} "$SRC_DIR" \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_FIND_ROOT_PATH_MODE_PACKAGE=ON \
    -DBUILD_RUNTIME_BROWSER=ON \
    -DBUILD_RUNTIME_NODE=OFF \
    -DCMAKE_INSTALL_PREFIX="$PREFIX" \
    -DLINK_LIBLZMA=ON \
    -DPY_VERSION="$PY_VER" \
    -DPYTHON_SITE_PACKAGES="$PREFIX/lib/python${PY_VER}/site-packages" \
    -DPython_INCLUDE_DIRS="$PREFIX/include/python${PY_VER}" \
    -DPython_LIBRARY="$PREFIX/lib/libpython${PY_VER}.a" \
    -DPython_LIBRARIES="$PREFIX/lib/libpython${PY_VER}.a" \
    -DPython_Interpreter_FOUND=TRUE \
    -DPython_EXECUTABLE="$BUILD_PREFIX/bin/python${PY_VER}" \
    -DPYTHON_MODULE_EXTENSION=.so \
    -DPYTHON_MODULE_DEBUG_POSTFIX="" \
    -DPYTHON_MODULE_EXT_SUFFIX=.so \
    -DPython_FOUND=TRUE \
    -DWASM64="$USE_WASM64"

emmake make -j"$NUM_JOBS"
emmake make install

echo ""
echo "pyjs built and installed into $PREFIX"
echo "  runtime: $PREFIX/lib_js/pyjs/pyjs_runtime_browser.{js,wasm}"
echo "  library: $PREFIX/lib/libpyjs.a"
