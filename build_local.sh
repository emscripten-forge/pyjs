#!/bin/bash
# Local build of pyjs
#
# Usage: ./build_local.sh [wasm32|wasm64] [--fresh] [--test]
#
#   --fresh   delete and recreate the environments and the build dir
#   --test    run the browser tests (main thread) with pyjs_code_runner
#
# Env overrides: NUM_JOBS, MAMBA_EXE,
#                SRC_DIR (pyjs source tree, default: this dir)
#
# Environments (all under build_root/):
#   build_prefix_<wasm>/   native env      environment-wasm-build-<wasm>.yml
#                          (emscripten compiler, cmake, pyjs_code_runner, ...)
#   host_prefix_<wasm>/    emscripten env  environment-wasm.yml
#                          (libpython-static, pybind11, ...; pyjs is
#                          installed into this prefix)
#   deploy_prefix_<wasm>/  emscripten env  environment-wasm-deploy.yml
#                          (runtime env the built pyjs runs against)
#   build_<wasm>/          cmake build dir
set -euo pipefail

########################################
# arguments
########################################
WASM_TYPE="wasm32"
FRESH=0
RUN_TESTS=0
for arg in "$@"; do
    case "$arg" in
        wasm32|wasm64) WASM_TYPE="$arg" ;;
        --fresh)       FRESH=1 ;;
        --test)        RUN_TESTS=1 ;;
        *)
            echo "Usage: $0 [wasm32|wasm64] [--fresh] [--test]"
            exit 1
            ;;
    esac
done

########################################
# configuration
########################################
THIS_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
SRC_DIR="${SRC_DIR:-$THIS_DIR}"
NUM_JOBS="${NUM_JOBS:-$(sysctl -n hw.ncpu 2>/dev/null || nproc)}"

PLATFORM="emscripten-$WASM_TYPE"

BUILD_ENV_FILE="$SRC_DIR/environment-wasm-build-$WASM_TYPE.yml"
HOST_ENV_FILE="$SRC_DIR/environment-wasm.yml"
DEPLOY_ENV_FILE="$SRC_DIR/environment-wasm-deploy.yml"

BUILD_ROOT="$THIS_DIR/build_root"
BUILD_PREFIX="$BUILD_ROOT/build_prefix_$WASM_TYPE"
HOST_PREFIX="$BUILD_ROOT/host_prefix_$WASM_TYPE"
DEPLOY_PREFIX="$BUILD_ROOT/deploy_prefix_$WASM_TYPE"
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
    rm -rf "$BUILD_PREFIX" "$HOST_PREFIX" "$DEPLOY_PREFIX" "$BUILD_DIR"
fi

# create_env <prefix> <env-file> [extra micromamba args...]
create_env() {
    local prefix="$1" env_file="$2"
    shift 2
    if [ ! -d "$prefix" ]; then
        echo "Creating environment at $prefix from $(basename "$env_file") $*"
        "$MAMBA_EXE" create -p "$prefix" -f "$env_file" --yes "$@"
    fi
}

########################################
# build (native) + host (emscripten) environments
########################################
create_env "$BUILD_PREFIX" "$BUILD_ENV_FILE"
create_env "$HOST_PREFIX"  "$HOST_ENV_FILE" --platform "$PLATFORM"

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

# CMAKE_ARGS (from the emscripten activation) sets the emscripten toolchain
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

########################################
# deploy (run) environment
########################################
create_env "$DEPLOY_PREFIX" "$DEPLOY_ENV_FILE" --platform "$PLATFORM"

########################################
# tests
########################################
if [ "$RUN_TESTS" = "1" ]; then
    cd "$THIS_DIR"
    playwright install chromium
    mkdir -p "$BUILD_DIR/host_work_dir"
    # the pyjs python module is mounted from the source tree,
    # the runtime (js/wasm) is taken from the build dir
    pyjs_code_runner run script \
        browser-main \
        --conda-env     "$DEPLOY_PREFIX" \
        --mount         "$SRC_DIR/tests:/tests" \
        --mount         "$SRC_DIR/module/pyjs:/lib/python${PY_VER}/site-packages/pyjs" \
        --script        main.py \
        --work-dir      /tests \
        --host-work-dir "$BUILD_DIR/host_work_dir" \
        --headless \
        --no-cache \
        --slow-mo 0 \
        --async-main \
        --pyjs-dir      "$BUILD_DIR"
fi
