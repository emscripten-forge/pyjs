#!/bin/bash
# Local build of pyjs
#
# Usage: ./build_local.sh [wasm32|wasm64] [--fresh] [--test] [--bench] [--docs]
#
#   --fresh   delete and recreate the environments and the build dir
#   --docs    build the documentation (sphinx + jupyterlite, wasm32 only):
#             pyjs is built into a separate docs host env, xeus-python is
#             built from source against it (the docs kernel), the html ends
#             up in build_root/docs_html (or DOCS_OUT_DIR).
#             With --test: smoke test of the docs instead of the pyjs tests
#             (build_utils/docs_smoke_test.py, for each of BROWSERS)
#   --test    run the browser tests with pyjs_code_runner
#   --bench   run the benchmarks in benchmarks/ and store the output in
#             build_root/benchmarks/<wasm>/<stamp>_<browser>_<backend>.{log,json}
#   (both run for every combination of BROWSERS x BACKENDS)
#
# Env overrides: NUM_JOBS, MAMBA_EXE,
#                SRC_DIR (pyjs source tree, default: this dir)
#                BACKENDS (default: "browser-main browser-worker")
#                BROWSERS (default: "chromium"; also: firefox webkit,
#                webkit is the engine behind Safari)
#                DEPLOY_ENV_FILE (env file of the run env the tests /
#                benchmarks run against, default: environment-wasm-deploy.yml)
#                PLAYWRIGHT_INSTALL_ARGS (extra args for `playwright install`,
#                e.g. --with-deps on CI)
#                BUILD_ENV_PREFIX (use this existing build env instead of
#                creating build_root/build_prefix_<wasm>; it is used as is,
#                never created or deleted by this script, e.g. on CI)
#                PYJS_CODE_RUNNER_DIR (local pyjs-code-runner checkout,
#                pip installed (editable) into the build env)
#                BENCH_FILTER (only run benchmarks whose "module::name"
#                contains this substring)
#                XEUS_PYTHON_REF (xeus-python tag used by --docs)
#                DOCS_OUT_DIR (html output of --docs)
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
#   (--docs: host_docs_prefix_<wasm>/ from environment-wasm.yml +
#    environment-wasm-docs.yml, build_docs_<wasm>/, build_xeus_python_<wasm>/,
#    src/xeus-python-<ref>/)
set -euo pipefail

########################################
# arguments
########################################
WASM_TYPE="wasm32"
FRESH=0
RUN_TESTS=0
RUN_BENCH=0
RUN_DOCS=0
for arg in "$@"; do
    case "$arg" in
        wasm32|wasm64) WASM_TYPE="$arg" ;;
        --fresh)       FRESH=1 ;;
        --test)        RUN_TESTS=1 ;;
        --bench)       RUN_BENCH=1 ;;
        --docs)        RUN_DOCS=1 ;;
        *)
            echo "Usage: $0 [wasm32|wasm64] [--fresh] [--test] [--bench] [--docs]"
            exit 1
            ;;
    esac
done

if [ "$RUN_DOCS" = "1" ] && [ "$WASM_TYPE" != "wasm32" ]; then
    echo "Error: --docs is only supported for wasm32"
    exit 1
fi

########################################
# configuration
########################################
THIS_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
SRC_DIR="${SRC_DIR:-$THIS_DIR}"
NUM_JOBS="${NUM_JOBS:-$(sysctl -n hw.ncpu 2>/dev/null || nproc)}"

PLATFORM="emscripten-$WASM_TYPE"

BUILD_ENV_FILE="$SRC_DIR/environment-wasm-build-$WASM_TYPE.yml"
HOST_ENV_FILE="$SRC_DIR/environment-wasm.yml"
DEPLOY_ENV_FILE="${DEPLOY_ENV_FILE:-$SRC_DIR/environment-wasm-deploy.yml}"

BUILD_ROOT="$THIS_DIR/build_root"
BUILD_ENV_PREFIX="${BUILD_ENV_PREFIX:-}"
if [ -n "$BUILD_ENV_PREFIX" ]; then
    BUILD_PREFIX="$BUILD_ENV_PREFIX"
else
    BUILD_PREFIX="$BUILD_ROOT/build_prefix_$WASM_TYPE"
fi
HOST_PREFIX="$BUILD_ROOT/host_prefix_$WASM_TYPE"
HOST_ENV_ARGS=()
# one run env per env file, e.g. environment-wasm-deploy.yml -> deploy_prefix_<wasm>
DEPLOY_ENV_NAME="$(basename "$DEPLOY_ENV_FILE" .yml)"
DEPLOY_ENV_NAME="${DEPLOY_ENV_NAME#environment-wasm-}"
DEPLOY_PREFIX="$BUILD_ROOT/${DEPLOY_ENV_NAME//-/_}_prefix_$WASM_TYPE"
BUILD_DIR="$BUILD_ROOT/build_$WASM_TYPE"
if [ "$RUN_DOCS" = "1" ]; then
    # docs: pyjs is installed into a host env which also has everything
    # needed to build / run xeus-python (the kernel of the docs jupyterlite)
    HOST_PREFIX="$BUILD_ROOT/host_docs_prefix_$WASM_TYPE"
    HOST_ENV_ARGS=(-f "$SRC_DIR/environment-wasm-docs.yml")
    BUILD_DIR="$BUILD_ROOT/build_docs_$WASM_TYPE"
fi
XEUS_PYTHON_REF="${XEUS_PYTHON_REF:-0.19.1}"
XEUS_PYTHON_SRC="$BUILD_ROOT/src/xeus-python-$XEUS_PYTHON_REF"
XEUS_PYTHON_BUILD_DIR="$BUILD_ROOT/build_xeus_python_$WASM_TYPE"
DOCS_OUT_DIR="${DOCS_OUT_DIR:-$BUILD_ROOT/docs_html}"
BENCH_OUT_DIR="$BUILD_ROOT/benchmarks/$WASM_TYPE"
# pyjs_code_runner backends used by --test / --bench
BACKENDS="${BACKENDS:-browser-main browser-worker}"
BROWSERS="${BROWSERS:-chromium}"
PYJS_CODE_RUNNER_DIR="${PYJS_CODE_RUNNER_DIR:-}"

########################################
# find micromamba / mamba
########################################
if [ -z "${MAMBA_EXE:-}" ]; then
    # type -P: only executables on PATH (micromamba is often also a shell function)
    MAMBA_EXE="$(type -P micromamba || type -P mamba || true)"
fi
if [ -z "$MAMBA_EXE" ] || [ ! -x "$MAMBA_EXE" ]; then
    echo "Error: micromamba/mamba not found (set MAMBA_EXE)."
    exit 1
fi

if [ "$FRESH" = "1" ]; then
    echo "Removing existing environments and build dir"
    rm -rf "$HOST_PREFIX" "$DEPLOY_PREFIX" "$BUILD_DIR"
    if [ "$RUN_DOCS" = "1" ]; then
        rm -rf "$XEUS_PYTHON_BUILD_DIR" "$DOCS_OUT_DIR"
    fi
    if [ -z "$BUILD_ENV_PREFIX" ]; then
        rm -rf "$BUILD_PREFIX"
    fi
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
if [ -n "$BUILD_ENV_PREFIX" ]; then
    if [ ! -d "$BUILD_ENV_PREFIX" ]; then
        echo "Error: BUILD_ENV_PREFIX=$BUILD_ENV_PREFIX does not exist."
        exit 1
    fi
    echo "Using existing build environment at $BUILD_ENV_PREFIX"
else
    create_env "$BUILD_PREFIX" "$BUILD_ENV_FILE"
fi
create_env "$HOST_PREFIX"  "$HOST_ENV_FILE" ${HOST_ENV_ARGS[@]+"${HOST_ENV_ARGS[@]}"} --platform "$PLATFORM"

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
# docs: xeus-python (built against this pyjs) + sphinx / jupyterlite
########################################
if [ "$RUN_DOCS" = "1" ]; then
    if [ ! -d "$XEUS_PYTHON_SRC" ]; then
        mkdir -p "$(dirname "$XEUS_PYTHON_SRC")"
        git clone --depth 1 --branch "$XEUS_PYTHON_REF" \
            https://github.com/jupyter-xeus/xeus-python "$XEUS_PYTHON_SRC"
    fi

    # as in the emscripten-forge xeus-python recipe:
    # remove the fake pythons and link python (+ its deps) statically.
    # PYTHONLIBS_FOUND / PYTHON_MODULE_EXTENSION / PYTHON_INCLUDE_DIR(S) make
    # pybind11 skip querying the (native, 64 bit) build python, the recipe
    # uses cross-python for that instead.
    rm -f "$PREFIX"/bin/python*
    XPYT_PYTHON_LIBRARIES="$PREFIX/lib/libbz2.a;$PREFIX/lib/libz.a;$PREFIX/lib/libsqlite3.a"
    XPYT_PYTHON_LIBRARIES+=";$PREFIX/lib/libffi.a;$PREFIX/lib/libzstd.a;$PREFIX/lib/libssl.a"
    XPYT_PYTHON_LIBRARIES+=";$PREFIX/lib/libcrypto.a;$PREFIX/lib/liblzma.a"
    for lib in expat mpdec Hacl_Hash_BLAKE2 Hacl_Hash_MD5 Hacl_Hash_SHA1 Hacl_Hash_SHA2 Hacl_Hash_SHA3; do
        XPYT_PYTHON_LIBRARIES+=";$PREFIX/lib/python${PY_VER}/static/lib$lib.a"
    done
    XPYT_PYTHON_LIBRARIES+=";$PREFIX/lib/libpython${PY_VER}.a"

    mkdir -p "$XEUS_PYTHON_BUILD_DIR"
    cd "$XEUS_PYTHON_BUILD_DIR"
    # shellcheck disable=SC2086
    emcmake cmake ${CMAKE_ARGS:-} "$XEUS_PYTHON_SRC" \
        -GNinja \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_PREFIX_PATH="$PREFIX" \
        -DCMAKE_INSTALL_PREFIX="$PREFIX" \
        -DPYTHON_LIBRARIES="$XPYT_PYTHON_LIBRARIES" \
        -DPYBIND11_PYTHON_VERSION="$PY_VER" \
        -DPYTHONLIBS_FOUND=TRUE \
        -DPYTHON_MODULE_EXTENSION=.so \
        -DPYTHON_INCLUDE_DIR="$PREFIX/include/python${PY_VER}" \
        -DPYTHON_INCLUDE_DIRS="$PREFIX/include/python${PY_VER}"
    ninja
    ninja install
    rm -rf "$PREFIX/share/jupyter/kernels/xpython-raw"
    echo "xeus-python $XEUS_PYTHON_REF built against this pyjs and installed into $PREFIX"

    # pyjs runtime + packed environment for the javascript kernel of the docs
    # jupyterlite, deployed as <html root>/pyjs-runtime/ (see docs/conf.py)
    create_env "$DEPLOY_PREFIX" "$DEPLOY_ENV_FILE" --platform "$PLATFORM"
    DOCS_EXTRA_DIR="$BUILD_ROOT/docs_extra"
    PYJS_RUNTIME_DIR="$DOCS_EXTRA_DIR/pyjs-runtime"
    rm -rf "$DOCS_EXTRA_DIR"
    mkdir -p "$PYJS_RUNTIME_DIR"
    cp "$BUILD_DIR/pyjs_runtime_browser.js" "$BUILD_DIR/pyjs_runtime_browser.wasm" "$PYJS_RUNTIME_DIR/"
    empack pack env \
        --env-prefix "$DEPLOY_PREFIX" \
        --relocate-prefix "/" \
        --outdir "$PYJS_RUNTIME_DIR"
    # the pyjs python module of this repository
    empack pack dir \
        --host-dir "$SRC_DIR/module/pyjs" \
        --mount-dir "/lib/python${PY_VER}/site-packages/pyjs" \
        --outname "pyjs_module.tar.gz" \
        --outdir "$PYJS_RUNTIME_DIR"
    empack pack append \
        --env-meta "$PYJS_RUNTIME_DIR/empack_env_meta.json" \
        --tarfile "$PYJS_RUNTIME_DIR/pyjs_module.tar.gz"
    export PYJS_DOCS_EXTRA_DIR="$DOCS_EXTRA_DIR"

    # docs/conf.py passes this env to jupyterlite-xeus as kernel env
    export PYJS_DOCS_KERNEL_PREFIX="$PREFIX"
    rm -rf "$DOCS_OUT_DIR"
    sphinx-build -b html "$SRC_DIR/docs" "$DOCS_OUT_DIR"
    echo ""
    echo "docs: $DOCS_OUT_DIR/index.html"

    # --docs --test: smoke test of the docs (pyjs in the jupyterlite kernels)
    DOCS_TEST_RET=0
    if [ "$RUN_TESTS" = "1" ]; then
        # shellcheck disable=SC2086
        playwright install ${PLAYWRIGHT_INSTALL_ARGS:-} $BROWSERS
        for BROWSER in $BROWSERS; do
            echo "========================================"
            echo "docs smoke test: $BROWSER"
            echo "========================================"
            python "$SRC_DIR/build_utils/docs_smoke_test.py" "$DOCS_OUT_DIR" --browser "$BROWSER" \
                || DOCS_TEST_RET=1
        done
    fi
    exit "$DOCS_TEST_RET"
fi

########################################
# deploy (run) environment
########################################
create_env "$DEPLOY_PREFIX" "$DEPLOY_ENV_FILE" --platform "$PLATFORM"

if [ "$RUN_TESTS" = "1" ] || [ "$RUN_BENCH" = "1" ]; then
    if [ -n "$PYJS_CODE_RUNNER_DIR" ]; then
        echo "Installing pyjs-code-runner from $PYJS_CODE_RUNNER_DIR"
        python -m pip install --no-deps --no-build-isolation -q -e "$PYJS_CODE_RUNNER_DIR"
    fi
    # shellcheck disable=SC2086
    playwright install ${PLAYWRIGHT_INSTALL_ARGS:-} $BROWSERS
fi

########################################
# tests
########################################
if [ "$RUN_TESTS" = "1" ]; then
    cd "$THIS_DIR"
    TEST_SUMMARY=()
    TEST_RET=0
    for BROWSER in $BROWSERS; do
    for BACKEND in $BACKENDS; do
        echo "========================================"
        echo "tests: $BROWSER / $BACKEND"
        echo "========================================"
        mkdir -p "$BUILD_DIR/host_work_dir_${BROWSER}_$BACKEND"
        # the pyjs python module is mounted from the source tree,
        # the runtime (js/wasm) is taken from the build dir
        set +e
        pyjs_code_runner run script \
            "$BACKEND" \
            --browser       "$BROWSER" \
            --conda-env     "$DEPLOY_PREFIX" \
            --mount         "$SRC_DIR/tests:/tests" \
            --mount         "$SRC_DIR/module/pyjs:/lib/python${PY_VER}/site-packages/pyjs" \
            --script        main.py \
            --work-dir      /tests \
            --host-work-dir "$BUILD_DIR/host_work_dir_${BROWSER}_$BACKEND" \
            --headless \
            --no-cache \
            --slow-mo 0 \
            --async-main \
            --pyjs-dir      "$BUILD_DIR"
        RET=$?
        set -e
        if [ "$RET" = "0" ]; then
            TEST_SUMMARY+=("  PASSED  $BROWSER / $BACKEND")
        else
            TEST_SUMMARY+=("  FAILED  $BROWSER / $BACKEND")
            TEST_RET=1
        fi
    done
    done
    echo ""
    echo "test summary ($WASM_TYPE):"
    printf '%s\n' "${TEST_SUMMARY[@]}"
    if [ "$RUN_BENCH" != "1" ] && [ "$TEST_RET" != "0" ]; then
        exit "$TEST_RET"
    fi
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
    for BROWSER in $BROWSERS; do
    for BACKEND in $BACKENDS; do
        echo "========================================"
        echo "benchmarks: $BROWSER / $BACKEND"
        echo "========================================"
        RUN_NAME="${BROWSER}_$BACKEND"
        mkdir -p "$BUILD_DIR/host_work_dir_bench_$RUN_NAME"
        BENCH_LOG="$BENCH_OUT_DIR/${STAMP}_$RUN_NAME.log"
        BENCH_JSON="$BENCH_OUT_DIR/${STAMP}_$RUN_NAME.json"

        set +e
        pyjs_code_runner run script \
            "$BACKEND" \
            --browser       "$BROWSER" \
            --conda-env     "$DEPLOY_PREFIX" \
            --mount         "$SRC_DIR/benchmarks:/benchmarks" \
            --mount         "$BUILD_DIR/bench_config:/bench_config" \
            --mount         "$SRC_DIR/module/pyjs:/lib/python${PY_VER}/site-packages/pyjs" \
            --script        main.py \
            --work-dir      /benchmarks \
            --host-work-dir "$BUILD_DIR/host_work_dir_bench_$RUN_NAME" \
            --headless \
            --no-cache \
            --slow-mo 0 \
            --async-main \
            --pyjs-dir      "$BUILD_DIR" 2>&1 | tee "$BENCH_LOG"
        RET=${PIPESTATUS[0]}
        set -e
        if [ "$RET" != "0" ]; then BENCH_RET=$RET; fi

        # extract the machine readable result line and add build metadata
        if ! python - "$BENCH_LOG" "$BENCH_JSON" "$WASM_TYPE" "$GIT_REV" "$STAMP" "$BACKEND" "$BROWSER" <<'PYEOF'
import json, sys
log, out, wasm_type, git_rev, stamp, backend, browser = sys.argv[1:]
marker = "PYJS_BENCH_RESULT_JSON:"
payload = None
with open(log) as f:
    for line in f:
        idx = line.find(marker)
        if idx != -1:
            payload = json.loads(line[idx + len(marker):])
if payload is None:
    sys.exit(f"no benchmark results found in {log}")
payload["build"] = dict(
    wasm_type=wasm_type, git_rev=git_rev, timestamp=stamp, backend=backend, browser=browser
)
with open(out, "w") as f:
    json.dump(payload, f, indent=2)
PYEOF
        then
            BENCH_RET=1
            continue
        fi
        ln -sf "$(basename "$BENCH_LOG")" "$BENCH_OUT_DIR/latest_$RUN_NAME.log"
        ln -sf "$(basename "$BENCH_JSON")" "$BENCH_OUT_DIR/latest_$RUN_NAME.json"
        echo ""
        echo "benchmark output: $BENCH_LOG"
        echo "benchmark json:   $BENCH_JSON"
    done
    done
    if [ "${TEST_RET:-0}" != "0" ]; then exit "$TEST_RET"; fi
    exit "$BENCH_RET"
fi
