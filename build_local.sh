#!/bin/bash
# Build, test and benchmark pyjs, build the npm package and the docs.
# The same script runs locally and on CI. It only needs micromamba (or mamba):
# all tools come from conda environments, created on the first run.
#
#   ./build_local.sh build wasm32|wasm64   build pyjs
#   ./build_local.sh test  wasm32|wasm64   build pyjs, run the tests in the browser
#   ./build_local.sh bench wasm32|wasm64   build pyjs, run the benchmarks in the browser
#   ./build_local.sh npm [--test]          build the npm package (+ run the tests on it)
#   ./build_local.sh docs                  build the npm package + the docs
#
#   --fresh   delete the environments and build directories first
#
# Environment variables (all optional):
#   BROWSERS          browsers for tests / benchmarks: chromium firefox webkit
#                     (default: chromium)
#   MODES             run in the browser main thread and / or a web worker:
#                     main worker (default: both)
#   ARCHS             architectures of `npm` / `docs` (default: wasm32 wasm64)
#   TEST_ENV          test packages: default | no-numpy (default: default)
#   DISABLE_JSPI=1    test like in a browser without JSPI
#   BENCH_FILTER      only run benchmarks whose name contains this text
#   NPM_TEST_BUNDLERS=0  `npm --test`: skip the apps built with bundlers
#   NPM_PACKAGE_NAME  default: @derthorsten/pyjs
#   DOCS_OUT_DIR      default: build_root/docs_html
#   BUILD_ENV_PREFIX  use this existing dev environment (CI)
#   EXTRA_CHANNELS    conda channels searched first, e.g. a local recipe build
#   PLAYWRIGHT_INSTALL_ARGS  e.g. --with-deps (CI)
#
# Everything is created in build_root/ (not in git):
#   dev_prefix/              native tools: emscripten, cmake, node, playwright, ...
#   host_prefix_<arch>/      what pyjs is built against (python, pybind11, ...)
#   build_<arch>/            cmake build directory of pyjs
#   test_env_<name>_<arch>/  python + test packages for the tests in the browser
#   npm_env_<arch>/          python + stdlib, shipped in the npm package
#   pages/                   web pages the tests run on (pyjs_test_driver)
#   npm/                     the npm package (npm/package/, npm/*.tgz)
set -euo pipefail

usage() {
    sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'
    exit 1
}

########################################
# command line
########################################
COMMAND="${1:-}"
shift || true
ARCH=""
FRESH=0
WITH_TESTS=0
for arg in "$@"; do
    case "$arg" in
        wasm32|wasm64) ARCH="$arg" ;;
        --fresh)       FRESH=1 ;;
        --test)        WITH_TESTS=1 ;;
        *)             usage ;;
    esac
done
case "$COMMAND" in
    build|test|bench) [ -n "$ARCH" ] || usage ;;
    npm|docs)         [ -z "$ARCH" ] || usage ;;  # always all of ARCHS
    *)                usage ;;
esac

########################################
# settings
########################################
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_ROOT="$SRC_DIR/build_root"
BROWSERS="${BROWSERS:-chromium}"
MODES="${MODES:-main worker}"
ARCHS="${ARCHS:-wasm32 wasm64}"
TEST_ENV="${TEST_ENV:-default}"
NPM_PACKAGE_NAME="${NPM_PACKAGE_NAME:-@derthorsten/pyjs}"
DOCS_OUT_DIR="${DOCS_OUT_DIR:-$BUILD_ROOT/docs_html}"
DEV_PREFIX="${BUILD_ENV_PREFIX:-$BUILD_ROOT/dev_prefix}"
NUM_JOBS="$(sysctl -n hw.ncpu 2>/dev/null || nproc)"
CHANNELS=(https://repo.prefix.dev/emscripten-forge/6x conda-forge)

# the packages the tests need (tests/sync/test_http.py: the http stack of
# e.g. scipy.datasets). Test pages with the raw runtime get them packed into
# the test env, npm pages install them at runtime (mambajs).
case "$TEST_ENV" in
    default)  TEST_PACKAGES=(numpy pytest urllib3 requests pyodide-http pooch) ;;
    no-numpy) TEST_PACKAGES=(pytest) ;;  # pyjs must work without (optional) numpy
    *)        echo "unknown TEST_ENV=$TEST_ENV (default | no-numpy)"; exit 1 ;;
esac
PYTHON_PACKAGES=(python "emscripten-abi==6.0.8")

MAMBA_EXE="${MAMBA_EXE:-$(type -P micromamba || type -P mamba || true)}"
[ -x "$MAMBA_EXE" ] || { echo "micromamba / mamba not found (set MAMBA_EXE)"; exit 1; }

########################################
# helpers
########################################
# a visible header in the (long) output
section() {
    printf '========================================\n%s\n========================================\n' "$*"
}

# conda channel arguments: EXTRA_CHANNELS first
channel_args() {
    local channel
    for channel in ${EXTRA_CHANNELS:-} "$@"; do
        printf -- '-c\n%s\n' "$channel"
    done
}

# create_env_from_file <prefix> <env file> [--platform <platform>]
# (only if the environment does not exist yet)
create_env_from_file() {
    local prefix="$1" file="$2"
    shift 2
    [ -d "$prefix" ] && return 0
    echo "creating $prefix from $(basename "$file")"
    # shellcheck disable=SC2046
    "$MAMBA_EXE" create --yes -p "$prefix" -f "$file" $(channel_args) "$@"
}

# create_env_from_packages <prefix> <platform> <package>...
# (only if the environment does not exist yet)
create_env_from_packages() {
    local prefix="$1" platform="$2"
    shift 2
    [ -d "$prefix" ] && return 0
    echo "creating $prefix: $*"
    # shellcheck disable=SC2046
    "$MAMBA_EXE" create --yes -p "$prefix" --platform "$platform" $(channel_args "${CHANNELS[@]}") "$@"
}

# install_browsers: the playwright browsers in BROWSERS (no-op if present)
install_browsers() {
    # shellcheck disable=SC2086
    playwright install ${PLAYWRIGHT_INSTALL_ARGS:-} $BROWSERS
}

# test_driver ...: creates and runs the test pages (pyjs_test_driver/)
test_driver() {
    (cd "$SRC_DIR" && python -m pyjs_test_driver "$@")
}

########################################
# the dev environment: created and activated once, for both architectures
########################################
if [ "$FRESH" = "1" ]; then
    echo "removing the environments and build directories"
    [ -n "${BUILD_ENV_PREFIX:-}" ] || rm -rf "$DEV_PREFIX"
    rm -rf "$BUILD_ROOT"/host_prefix_* "$BUILD_ROOT"/build_wasm* "$BUILD_ROOT"/test_env_* \
           "$BUILD_ROOT"/npm_env_* "$BUILD_ROOT"/pages
fi
if [ -n "${BUILD_ENV_PREFIX:-}" ]; then
    [ -d "$BUILD_ENV_PREFIX" ] || { echo "BUILD_ENV_PREFIX=$BUILD_ENV_PREFIX does not exist"; exit 1; }
else
    create_env_from_file "$DEV_PREFIX" "$SRC_DIR/environment-dev.yml"
fi

# The activation of emscripten-core sets the compiler flags. Flags of an
# earlier activation (e.g. in the calling shell, maybe with -m64) must not
# leak in. Activation scripts are not `set -u` safe.
unset CONDA_FORGE_EMSCRIPTEN_ACTIVATED EMCC_CFLAGS CFLAGS CXXFLAGS LDFLAGS 2>/dev/null || true
set +u
eval "$("$MAMBA_EXE" shell hook -s bash)"
micromamba activate "$DEV_PREFIX"
set -u
# CMakeLists.txt runs $CONDA_PREFIX/bin/python (merge_js.py), empack finds
# its config via CONDA_PREFIX
export CONDA_PREFIX="$DEV_PREFIX"
EMCC_CFLAGS_WASM32="$EMCC_CFLAGS"

########################################
# one architecture
########################################
# use_arch <wasm32|wasm64>: the paths and compiler flags of one architecture,
# creates its host environment.
#
# The dev env only has emscripten-core, whose flags are the wasm32 flags. For
# wasm64 every emcc call needs -m64 (EMCC_CFLAGS); that is all the
# emscripten_emscripten-wasm64 package would add.
use_arch() {
    ARCH="$1"
    PLATFORM="emscripten-$ARCH"
    export PREFIX="$BUILD_ROOT/host_prefix_$ARCH"
    BUILD_DIR="$BUILD_ROOT/build_$ARCH"
    TEST_ENV_PREFIX="$BUILD_ROOT/test_env_${TEST_ENV//-/_}_$ARCH"
    VANILLA_PAGE="$BUILD_ROOT/pages/vanilla_$ARCH"
    if [ "$ARCH" = "wasm64" ]; then
        export EMCC_CFLAGS="$EMCC_CFLAGS_WASM32 -m64"
    else
        export EMCC_CFLAGS="$EMCC_CFLAGS_WASM32"
    fi
    export LDFLAGS="-L$PREFIX/lib"
    section "$ARCH (EMCC_CFLAGS=$EMCC_CFLAGS)"

    create_env_from_file "$PREFIX" "$SRC_DIR/environment-host.yml" --platform "$PLATFORM"
    PY_VER="$(basename "$PREFIX"/include/python3.* | sed 's/^python//')"  # e.g. 3.14
}

# build_pyjs: build pyjs for ARCH and install it into its host env
build_pyjs() {
    local wasm64=FALSE cmake_m64=()
    if [ "$ARCH" = "wasm64" ]; then
        wasm64=TRUE
        # the emscripten toolchain file decides 32 / 64 bit from CMAKE_C_FLAGS
        cmake_m64=(-DCMAKE_C_FLAGS=-m64 -DCMAKE_CXX_FLAGS=-m64)
    fi
    mkdir -p "$BUILD_DIR"
    (
        cd "$BUILD_DIR"
        emcmake cmake "$SRC_DIR" \
            -DCMAKE_BUILD_TYPE=Release \
            -DCMAKE_PREFIX_PATH="$PREFIX" \
            -DCMAKE_FIND_ROOT_PATH="$PREFIX" \
            -DCMAKE_FIND_ROOT_PATH_MODE_PACKAGE=ON \
            -DCMAKE_INSTALL_PREFIX="$PREFIX" \
            ${cmake_m64[@]+"${cmake_m64[@]}"} \
            -DWASM64="$wasm64" \
            -DBUILD_RUNTIME_BROWSER=ON \
            -DBUILD_RUNTIME_NODE=OFF \
            -DLINK_LIBLZMA=ON \
            -DPY_VERSION="$PY_VER" \
            -DPYTHON_SITE_PACKAGES="$PREFIX/lib/python$PY_VER/site-packages" \
            -DPython_INCLUDE_DIRS="$PREFIX/include/python$PY_VER" \
            -DPython_LIBRARY="$PREFIX/lib/libpython$PY_VER.a" \
            -DPython_LIBRARIES="$PREFIX/lib/libpython$PY_VER.a" \
            -DPython_EXECUTABLE="$DEV_PREFIX/bin/python$PY_VER" \
            -DPython_Interpreter_FOUND=TRUE \
            -DPython_FOUND=TRUE \
            -DPYTHON_MODULE_EXTENSION=.so \
            -DPYTHON_MODULE_EXT_SUFFIX=.so \
            -DPYTHON_MODULE_DEBUG_POSTFIX=""
        emmake make -j"$NUM_JOBS"
        emmake make install
    )
    echo "pyjs ($ARCH): $BUILD_DIR/pyjs_runtime_browser.{js,wasm}"
}

# pack_runtime <env prefix> <out dir> [empack args...]: the runtime of this
# build + the env packed by empack + the pyjs python module of this repository
pack_runtime() {
    local env="$1" out="$2"
    shift 2
    rm -rf "$out"
    mkdir -p "$out"
    cp "$BUILD_DIR/pyjs_runtime_browser.js" "$BUILD_DIR/pyjs_runtime_browser.wasm" "$out/"
    empack pack env --env-prefix "$env" --relocate-prefix / --outdir "$out" "$@"
    empack pack dir --host-dir "$SRC_DIR/module/pyjs" \
        --mount-dir "/lib/python$PY_VER/site-packages/pyjs" \
        --outname pyjs_module.tar.gz --outdir "$out"
    empack pack append --env-meta "$out/empack_env_meta.json" --tarfile "$out/pyjs_module.tar.gz"
}

# build_vanilla_page: the test page with the raw runtime of this build and the
# test packages packed by empack (VANILLA_PAGE)
build_vanilla_page() {
    create_env_from_packages "$TEST_ENV_PREFIX" "$PLATFORM" "${PYTHON_PACKAGES[@]}" "${TEST_PACKAGES[@]}"
    pack_runtime "$TEST_ENV_PREFIX" "$BUILD_ROOT/pages/vanilla_assets_$ARCH"
    test_driver build-page vanilla --assets "$BUILD_ROOT/pages/vanilla_assets_$ARCH" --out "$VANILLA_PAGE"
}

# run_tests <label> <page dir> <browsers> <modes> [test_driver run args...]:
# the test suite on a page, for every browser and mode. Adds a line per run
# to SUMMARY, returns 1 if one failed.
SUMMARY=()
run_tests() {
    local label="$1" page="$2" browsers="$3" modes="$4" browser mode ret=0
    shift 4
    for browser in $browsers; do
        for mode in $modes; do
            section "tests $label: $browser / $mode"
            if test_driver run "$page" --browser "$browser" --mode "$mode" "$@"; then
                SUMMARY+=("  PASSED  $label / $browser / $mode")
            else
                SUMMARY+=("  FAILED  $label / $browser / $mode")
                ret=1
            fi
        done
    done
    return "$ret"
}

# print_summary: one line per test run (see run_tests)
print_summary() {
    printf '\ntest summary (TEST_ENV=%s, DISABLE_JSPI=%s):\n' "$TEST_ENV" "${DISABLE_JSPI:-0}"
    printf '%s\n' "${SUMMARY[@]}"
}

########################################
# npm package
########################################
# build_npm_package: per architecture the runtime + python / stdlib / the pyjs
# module packed by empack, then npm/build.mjs assembles one package of all
# ARCHS: build_root/npm/package/ and build_root/npm/*.tgz
build_npm_package() {
    local arch stages=() version
    for arch in $ARCHS; do
        use_arch "$arch"
        build_pyjs
        create_env_from_packages "$BUILD_ROOT/npm_env_$ARCH" "$PLATFORM" "${PYTHON_PACKAGES[@]}"
        # npm/empack_config.yaml drops CPython's test suite etc.
        pack_runtime "$BUILD_ROOT/npm_env_$ARCH" "$BUILD_ROOT/npm/stage/$ARCH" \
            --config "$SRC_DIR/npm/empack_config.yaml" --no-use-cache
        # + the channels and the python version for mambajs (packages installed at runtime)
        python "$SRC_DIR/build_utils/npm_env_meta.py" "$BUILD_ROOT/npm/stage/$ARCH/empack_env_meta.json" \
            "${CHANNELS[@]}"
        stages+=(--stage "$ARCH=$BUILD_ROOT/npm/stage/$ARCH")
    done

    version="$(sed -n 's/^project(pyjs VERSION \([0-9.]*\).*/\1/p' "$SRC_DIR/CMakeLists.txt")"
    (cd "$SRC_DIR/npm" && npm ci --no-audit --no-fund &&
        node build.mjs --out "$BUILD_ROOT/npm/package" --name "$NPM_PACKAGE_NAME" \
            --version "$version" "${stages[@]}")
    rm -f "$BUILD_ROOT"/npm/*.tgz
    (cd "$BUILD_ROOT/npm/package" && npm pack --pack-destination "$BUILD_ROOT/npm")
    echo "npm package: $BUILD_ROOT/npm/package"
    echo "  publish:   cd $BUILD_ROOT/npm/package && npm publish --access public"
}

# test_npm_package: the test suite on the npm package (both architectures)
# and on apps built with the common bundlers around it
test_npm_package() {
    local arch bundler ret=0 tgz
    tgz="$(ls "$BUILD_ROOT"/npm/*.tgz)"
    install_browsers
    for arch in $ARCHS; do
        test_driver build-page npm --package "$BUILD_ROOT/npm/package" --arch "$arch" \
            --packages "${TEST_PACKAGES[@]}" --out "$BUILD_ROOT/pages/npm_$arch"
        # the npm pages need the network (test packages via mambajs from
        # prefix.dev): retry a failed setup, never failed tests
        run_tests "npm $arch" "$BUILD_ROOT/pages/npm_$arch" "$BROWSERS" "$MODES" --retries 5 || ret=1
    done
    # the bundled app does not depend on the browser: the first browser, main thread
    if [ "${NPM_TEST_BUNDLERS:-1}" = "1" ]; then
        for bundler in vite webpack rollup esbuild parcel; do
            if test_driver build-page "$bundler" --tgz "$tgz" --packages "${TEST_PACKAGES[@]}" \
                    --work-dir "$BUILD_ROOT/pages/bundler_projects" --out "$BUILD_ROOT/pages/$bundler"; then
                run_tests "$bundler" "$BUILD_ROOT/pages/$bundler" "${BROWSERS%% *}" main --retries 5 || ret=1
            else
                SUMMARY+=("  FAILED  $bundler (building the page)")
                ret=1
            fi
        done
    fi
    print_summary
    return "$ret"
}

########################################
# the commands
########################################
cmd_build() {
    use_arch "$ARCH"
    build_pyjs
}

cmd_test() {
    local jspi=() ret=0
    [ "${DISABLE_JSPI:-0}" = "1" ] && jspi=(--disable-jspi)
    use_arch "$ARCH"
    build_pyjs
    build_vanilla_page
    install_browsers
    run_tests "vanilla $ARCH" "$VANILLA_PAGE" "$BROWSERS" "$MODES" ${jspi[@]+"${jspi[@]}"} || ret=1
    print_summary
    return "$ret"
}

# results: build_root/benchmarks/<arch>/<time>_<git rev>_<browser>_<mode>.{log,json}
cmd_bench() {
    local out="$BUILD_ROOT/benchmarks/$ARCH" rev stamp browser mode name ret=0
    use_arch "$ARCH"
    build_pyjs
    build_vanilla_page
    install_browsers
    mkdir -p "$out"
    rev="$(git -C "$SRC_DIR" rev-parse --short HEAD 2>/dev/null || echo unknown)"
    [ -z "$(git -C "$SRC_DIR" status --porcelain --untracked-files=no 2>/dev/null)" ] || rev="$rev-dirty"
    stamp="$(date +%Y%m%d-%H%M%S)_$rev"
    for browser in $BROWSERS; do
        for mode in $MODES; do
            section "benchmarks $ARCH: $browser / $mode"
            name="${browser}_$mode"
            test_driver run "$VANILLA_PAGE" --entry benchmarks --browser "$browser" --mode "$mode" \
                --option "filter=${BENCH_FILTER:-}" \
                --result-json "$out/${stamp}_$name.json" \
                --meta "wasm_type=$ARCH" --meta "git_rev=$rev" --meta "timestamp=$stamp" \
                --meta "mode=$mode" --meta "browser=$browser" 2>&1 | tee "$out/${stamp}_$name.log" || ret=1
            ln -sf "${stamp}_$name.log" "$out/latest_$name.log"
            ln -sf "${stamp}_$name.json" "$out/latest_$name.json"
        done
    done
    echo "benchmark results: $out/"
    return "$ret"
}

cmd_npm() {
    build_npm_package
    [ "$WITH_TESTS" = "0" ] || test_npm_package
}

# the docs + the npm package next to them (the playground loads it)
cmd_docs() {
    build_npm_package
    rm -rf "$BUILD_ROOT/docs_extra" "$DOCS_OUT_DIR"
    mkdir -p "$BUILD_ROOT/docs_extra"
    cp -R "$BUILD_ROOT/npm/package" "$BUILD_ROOT/docs_extra/pyjs"
    PYJS_DOCS_EXTRA_DIR="$BUILD_ROOT/docs_extra" NPM_PACKAGE_NAME="$NPM_PACKAGE_NAME" \
        sphinx-build -b html "$SRC_DIR/docs" "$DOCS_OUT_DIR"
    echo "docs: $DOCS_OUT_DIR/index.html"
}

"cmd_$COMMAND"
