#!/bin/bash
# Local build of pyjs
#
# Usage: ./build_local.sh [wasm32|wasm64] [--fresh] [--test] [--bench]
#
#   --fresh   delete and recreate the environments and the build dir
#   --test    run the browser tests with pyjs_code_runner
#   --bench   run the benchmarks in benchmarks/ and store the output in
#             build_root/benchmarks/<wasm>/<stamp>_<backend>.{log,json}
#   (both run in the browser main thread and in a worker, see BACKENDS)
#
# Env overrides: NUM_JOBS, MAMBA_EXE,
#                SRC_DIR (pyjs source tree, default: this dir)
#                BACKENDS (default: "browser-main browser-worker")
#                BENCH_FILTER (only run benchmarks whose "module::name"
#                contains this substring)
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
RUN_BENCH=0
for arg in "$@"; do
    case "$arg" in
        wasm32|wasm64) WASM_TYPE="$arg" ;;
        --fresh)       FRESH=1 ;;
        --test)        RUN_TESTS=1 ;;
        --bench)       RUN_BENCH=1 ;;
        *)
            echo "Usage: $0 [wasm32|wasm64] [--fresh] [--test] [--bench]"
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
BENCH_OUT_DIR="$BUILD_ROOT/benchmarks/$WASM_TYPE"
# pyjs_code_runner backends used by --test / --bench
BACKENDS="${BACKENDS:-browser-main browser-worker}"

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

if [ "$RUN_TESTS" = "1" ] || [ "$RUN_BENCH" = "1" ]; then
    playwright install chromium
fi

########################################
# tests
########################################
if [ "$RUN_TESTS" = "1" ]; then
    cd "$THIS_DIR"
    for BACKEND in $BACKENDS; do
        echo "========================================"
        echo "tests: $BACKEND"
        echo "========================================"
        mkdir -p "$BUILD_DIR/host_work_dir_$BACKEND"
        # the pyjs python module is mounted from the source tree,
        # the runtime (js/wasm) is taken from the build dir
        pyjs_code_runner run script \
            "$BACKEND" \
            --conda-env     "$DEPLOY_PREFIX" \
            --mount         "$SRC_DIR/tests:/tests" \
            --mount         "$SRC_DIR/module/pyjs:/lib/python${PY_VER}/site-packages/pyjs" \
            --script        main.py \
            --work-dir      /tests \
            --host-work-dir "$BUILD_DIR/host_work_dir_$BACKEND" \
            --headless \
            --no-cache \
            --slow-mo 0 \
            --async-main \
            --pyjs-dir      "$BUILD_DIR"
    done
fi

########################################
# benchmarks
########################################
if [ "$RUN_BENCH" = "1" ]; then
    cd "$THIS_DIR"
    mkdir -p "$BUILD_DIR/bench_config" "$BENCH_OUT_DIR"

    # config read by benchmarks/main.py (mounted at /bench_config)
    BENCH_FILTER="${BENCH_FILTER:-}" python -c '
import json, os, sys
cfg = {}
if os.environ["BENCH_FILTER"]:
    cfg["filter"] = os.environ["BENCH_FILTER"]
json.dump(cfg, open(sys.argv[1], "w"))
' "$BUILD_DIR/bench_config/config.json"

    GIT_REV="$(git -C "$SRC_DIR" rev-parse --short HEAD 2>/dev/null || echo unknown)"
    if [ -n "$(git -C "$SRC_DIR" status --porcelain --untracked-files=no 2>/dev/null)" ]; then
        GIT_REV="$GIT_REV-dirty"
    fi
    STAMP="$(date +%Y%m%d-%H%M%S)_$GIT_REV"

    BENCH_RET=0
    for BACKEND in $BACKENDS; do
        echo "========================================"
        echo "benchmarks: $BACKEND"
        echo "========================================"
        mkdir -p "$BUILD_DIR/host_work_dir_bench_$BACKEND"
        BENCH_LOG="$BENCH_OUT_DIR/${STAMP}_$BACKEND.log"
        BENCH_JSON="$BENCH_OUT_DIR/${STAMP}_$BACKEND.json"

        set +e
        pyjs_code_runner run script \
            "$BACKEND" \
            --conda-env     "$DEPLOY_PREFIX" \
            --mount         "$SRC_DIR/benchmarks:/benchmarks" \
            --mount         "$BUILD_DIR/bench_config:/bench_config" \
            --mount         "$SRC_DIR/module/pyjs:/lib/python${PY_VER}/site-packages/pyjs" \
            --script        main.py \
            --work-dir      /benchmarks \
            --host-work-dir "$BUILD_DIR/host_work_dir_bench_$BACKEND" \
            --headless \
            --no-cache \
            --slow-mo 0 \
            --async-main \
            --pyjs-dir      "$BUILD_DIR" 2>&1 | tee "$BENCH_LOG"
        RET=${PIPESTATUS[0]}
        set -e
        if [ "$RET" != "0" ]; then BENCH_RET=$RET; fi

        # extract the machine readable result line and add build metadata
        python - "$BENCH_LOG" "$BENCH_JSON" "$WASM_TYPE" "$GIT_REV" "$STAMP" "$BACKEND" <<'PYEOF'
import json, sys
log, out, wasm_type, git_rev, stamp, backend = sys.argv[1:]
marker = "PYJS_BENCH_RESULT_JSON:"
payload = None
with open(log) as f:
    for line in f:
        idx = line.find(marker)
        if idx != -1:
            payload = json.loads(line[idx + len(marker):])
if payload is None:
    sys.exit(f"no benchmark results found in {log}")
payload["build"] = dict(wasm_type=wasm_type, git_rev=git_rev, timestamp=stamp, backend=backend)
with open(out, "w") as f:
    json.dump(payload, f, indent=2)
PYEOF
        ln -sf "$(basename "$BENCH_LOG")" "$BENCH_OUT_DIR/latest_$BACKEND.log"
        ln -sf "$(basename "$BENCH_JSON")" "$BENCH_OUT_DIR/latest_$BACKEND.json"
        echo ""
        echo "benchmark output: $BENCH_LOG"
        echo "benchmark json:   $BENCH_JSON"
    done
    exit "$BENCH_RET"
fi
