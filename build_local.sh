#!/bin/bash
# Build / test / benchmark pyjs, build the docs and the npm package.
# Used locally and on CI. Needs only micromamba (or mamba).
#
#   ./build_local.sh build wasm32|wasm64   build pyjs (installed into the host env)
#   ./build_local.sh test  wasm32|wasm64   build + browser tests (tests/)
#   ./build_local.sh bench wasm32|wasm64   build + benchmarks (benchmarks/)
#   ./build_local.sh docs [--test]         docs: sphinx + jupyterlite (all ARCHS)
#   ./build_local.sh npm  [--test]         npm package (all ARCHS)
#   --fresh                                recreate envs + build dirs first
#
# Env vars:
#   BROWSERS        chromium firefox webkit          (default: chromium)
#   BACKENDS        browser-main browser-worker      (default: both)
#   ARCHS           archs of docs / npm              (default: "wasm32 wasm64")
#   TEST_ENV        default | no-numpy               (packages of the test env)
#   DISABLE_JSPI=1  test with JSPI switched off at runtime
#   BENCH_FILTER    only benchmarks whose "module::name" contains it
#   BUILD_ENV_PREFIX  existing dev env to use (CI), never created / deleted
#   EXTRA_CHANNELS  channels searched first when creating envs
#   PYJS_CODE_RUNNER_DIR  pyjs-code-runner checkout, pip -e installed
#   PLAYWRIGHT_INSTALL_ARGS  e.g. --with-deps (CI)
#   XEUS_PYTHON_REF, DOCS_OUT_DIR                    (docs)
#   NPM_PACKAGE_NAME (default @derthorsten/pyjs), NPM_MINIFY=0,
#   NPM_TEST_NETWORK=0, NPM_TEST_BUNDLERS=0          (npm)
#   NUM_JOBS, MAMBA_EXE
#
# Everything lives in build_root/ (see CLAUDE.md):
#   dev_prefix/             native env, one for both archs (environment-dev.yml)
#   host_prefix_<wasm>/     emscripten env pyjs is built against + installed into,
#                           + the xeus-python deps of the docs (environment-host.yml)
#   deploy_prefix_<wasm>/   env the tests / benchmarks run in (DEPLOY_SPECS;
#                           deploy_no_numpy_prefix_<wasm>/ for TEST_ENV=no-numpy)
#   npm_env_prefix_<wasm>/  env shipped in the npm package (NPM_ENV_SPECS)
#   build_<wasm>/, build_xeus_python_<wasm>/   cmake build dirs
set -euo pipefail

usage() { sed -n '4,10p' "$0" | sed 's/^# \{0,1\}//'; exit 1; }

########################################
# arguments
########################################
COMMAND="${1:-}"
[ -n "$COMMAND" ] || usage
shift
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
    docs|npm)         [ -z "$ARCH" ] || { echo "$COMMAND builds all ARCHS, no arch argument"; exit 1; } ;;
    *)                usage ;;
esac

########################################
# configuration
########################################
SRC_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
BUILD_ROOT="$SRC_DIR/build_root"
NUM_JOBS="${NUM_JOBS:-$(sysctl -n hw.ncpu 2>/dev/null || nproc)}"
BROWSERS="${BROWSERS:-chromium}"
BACKENDS="${BACKENDS:-browser-main browser-worker}"
ARCHS="${ARCHS:-wasm32 wasm64}"
EMSCRIPTEN_VERSION="6.0.8"
# channels of the envs created from package lists (EXTRA_CHANNELS come first)
ENV_CHANNELS=(https://repo.prefix.dev/emscripten-forge/6x conda-forge)

TEST_ENV="${TEST_ENV:-default}"
case "$TEST_ENV" in
    # + the http stack of tests/tests/test_http.py (what scipy.datasets uses)
    default)  DEPLOY_SPECS=(python "emscripten-abi==$EMSCRIPTEN_VERSION" numpy pytest
                            urllib3 requests pyodide-http pooch) ;;
    # pyjs must work without (optional) numpy
    no-numpy) DEPLOY_SPECS=(python "emscripten-abi==$EMSCRIPTEN_VERSION" pytest) ;;
    *)        echo "unknown TEST_ENV=$TEST_ENV (default | no-numpy)"; exit 1 ;;
esac
# the env shipped in the npm package: python + stdlib only
NPM_ENV_SPECS=(python "emscripten-abi==$EMSCRIPTEN_VERSION")

DEV_PREFIX="${BUILD_ENV_PREFIX:-$BUILD_ROOT/dev_prefix}"
XEUS_PYTHON_REF="${XEUS_PYTHON_REF:-0.19.1}"
DOCS_OUT_DIR="${DOCS_OUT_DIR:-$BUILD_ROOT/docs_html}"
NPM_ROOT="$BUILD_ROOT/npm"
NPM_PACKAGE_NAME="${NPM_PACKAGE_NAME:-@derthorsten/pyjs}"

if [ -z "${MAMBA_EXE:-}" ]; then
    # type -P: only executables on PATH (micromamba is often also a shell function)
    MAMBA_EXE="$(type -P micromamba || type -P mamba || true)"
fi
[ -x "${MAMBA_EXE:-}" ] || { echo "micromamba / mamba not found (set MAMBA_EXE)"; exit 1; }

########################################
# helpers
########################################
section() { printf '========================================\n%s\n========================================\n' "$*"; }

# create_env <prefix> <platform> (-f <env file> | <spec>...): only if missing;
# envs without file get ENV_CHANNELS, EXTRA_CHANNELS are searched first
create_env() {
    local prefix="$1" platform="$2"
    shift 2
    [ -d "$prefix" ] && return 0
    local args=() channel
    for channel in ${EXTRA_CHANNELS:-}; do args+=(-c "$channel"); done
    if [ "$1" != "-f" ]; then
        for channel in "${ENV_CHANNELS[@]}"; do args+=(-c "$channel"); done
    fi
    [ "$platform" = "native" ] || args+=(--platform "$platform")
    echo "creating $prefix: $*"
    "$MAMBA_EXE" create -p "$prefix" --yes ${args[@]+"${args[@]}"} "$@"
}

########################################
# dev env: created + activated once, for all archs
########################################
if [ "$FRESH" = "1" ]; then
    echo "removing envs and build dirs"
    if [ -z "${BUILD_ENV_PREFIX:-}" ]; then rm -rf "$DEV_PREFIX"; fi
    rm -rf "$BUILD_ROOT"/host_prefix_wasm* "$BUILD_ROOT"/deploy_*prefix_wasm* \
           "$BUILD_ROOT"/npm_env_prefix_wasm* "$BUILD_ROOT"/build_wasm* "$BUILD_ROOT"/build_xeus_python_wasm*
fi
if [ -n "${BUILD_ENV_PREFIX:-}" ]; then
    [ -d "$BUILD_ENV_PREFIX" ] || { echo "BUILD_ENV_PREFIX=$BUILD_ENV_PREFIX does not exist"; exit 1; }
else
    create_env "$DEV_PREFIX" native -f "$SRC_DIR/environment-dev.yml"
fi

# flags of an earlier activation (e.g. of the calling shell) must not leak in
unset CONDA_FORGE_EMSCRIPTEN_ACTIVATED CONDA_FORGE_EMSCRIPTEN_WASM_32_ACTIVATED \
      CONDA_FORGE_EMSCRIPTEN_WASM_64_ACTIVATED EMCC_CFLAGS EMCC_FLAGS CFLAGS CXXFLAGS \
      LDFLAGS HOST MESON_CROSS_FILE CMAKE_ARGS PREFIX 2>/dev/null || true
set +u  # activation scripts are not nounset-safe
eval "$("$MAMBA_EXE" shell hook -s bash)"
micromamba activate "$DEV_PREFIX"
set -u
# CMakeLists.txt runs $ENV{CONDA_PREFIX}/bin/python (merge_js.py); empack
# finds its default config via CONDA_PREFIX
export CONDA_PREFIX="$DEV_PREFIX"
# the EMCC_CFLAGS of emscripten-core (= wasm32), extended by use_arch
EMCC_CFLAGS_BASE="$EMCC_CFLAGS"

if [ -n "${PYJS_CODE_RUNNER_DIR:-}" ]; then
    python -m pip install --no-deps --no-build-isolation -q -e "$PYJS_CODE_RUNNER_DIR"
fi

########################################
# per architecture
########################################
# use_arch <wasm32|wasm64>: env vars + host env of one architecture.
#
# The dev env has emscripten-core only (its activation = the wasm32 flags).
# What the emscripten_emscripten-wasm64 package adds in its activation is done
# here: -m64 for every emcc call (EMCC_CFLAGS) and in the compiler / linker
# flags. For cmake -m64 must be in CMAKE_C_FLAGS on the command line: the
# emscripten toolchain file decides 32 / 64 bit from it *before* CFLAGS of
# the environment are applied (with CFLAGS only, the first configure of a
# fresh build dir is 32 bit).
use_arch() {
    ARCH="$1"
    PLATFORM="emscripten-$ARCH"
    export PREFIX="$BUILD_ROOT/host_prefix_$ARCH"
    BUILD_DIR="$BUILD_ROOT/build_$ARCH"
    if [ "$TEST_ENV" = "default" ]; then
        DEPLOY_PREFIX="$BUILD_ROOT/deploy_prefix_$ARCH"
    else
        DEPLOY_PREFIX="$BUILD_ROOT/deploy_$(echo "$TEST_ENV" | tr - _)_prefix_$ARCH"
    fi
    local m64=""
    [ "$ARCH" = "wasm64" ] && m64="-m64"

    export EMCC_CFLAGS="$EMCC_CFLAGS_BASE${m64:+ $m64}"
    export CFLAGS="$m64" CXXFLAGS="$m64"
    export LDFLAGS="-L$PREFIX/lib -Wl,-rpath,/lib${m64:+ $m64}"
    export HOST="$ARCH-unknown-emscripten"
    CMAKE_ARGS=(
        -DCMAKE_TOOLCHAIN_FILE="$EMSCRIPTEN_FORGE_EMSDK_DIR/upstream/emscripten/cmake/Modules/Platform/Emscripten.cmake"
        -DCMAKE_PREFIX_PATH="$PREFIX"
        -DCMAKE_FIND_ROOT_PATH="$PREFIX"
        -DCMAKE_INSTALL_PREFIX="$PREFIX"
        -DCMAKE_PLATFORM_NO_VERSIONED_SONAME=ON
        -DCMAKE_POSITION_INDEPENDENT_CODE=ON
        -DCMAKE_BUILD_TYPE=Release
    )
    if [ -n "$m64" ]; then
        CMAKE_ARGS+=(-DCMAKE_C_FLAGS=-m64 -DCMAKE_CXX_FLAGS=-m64)
    fi
    section "$ARCH (EMCC_CFLAGS=$EMCC_CFLAGS)"

    create_env "$PREFIX" "$PLATFORM" -f "$SRC_DIR/environment-host.yml"
    if [ "$ARCH" = "wasm64" ]; then
        fix_wasm64_cmake_configs
    fi
    PY_VER=$(basename -- "$PREFIX"/include/python* | sed 's/^python//')
}

# The wasm64 packages of the channel (xeus, xeus-lite, zlib, ...) are 64 bit,
# but their cmake package version files come from a 32 bit configure (see
# use_arch): they claim CMAKE_SIZEOF_VOID_P 4 and reject 64 bit projects.
# Disable that check in this env (sed -i writes a new file: the hardlinked
# file in the micromamba package cache stays untouched).
# TODO: remove once the packages are rebuilt (emscripten-forge/recipes)
fix_wasm64_cmake_configs() {
    local check='^if(NOT CMAKE_SIZEOF_VOID_P STREQUAL "4")' file
    for file in $(grep -rl --include='*ConfigVersion.cmake' "$check" \
                      "$PREFIX/lib/cmake" "$PREFIX/share/cmake" 2>/dev/null || true); do
        sed -i.bak "s/$check/if(FALSE) # build_local.sh: wasm64 package with a 32 bit cmake config/" "$file"
        rm -f "$file.bak"
    done
}

build_pyjs() {
    mkdir -p "$BUILD_DIR"
    (
        cd "$BUILD_DIR"
        emcmake cmake "${CMAKE_ARGS[@]}" "$SRC_DIR" \
            -DCMAKE_FIND_ROOT_PATH_MODE_PACKAGE=ON \
            -DBUILD_RUNTIME_BROWSER=ON \
            -DBUILD_RUNTIME_NODE=OFF \
            -DLINK_LIBLZMA=ON \
            -DPY_VERSION="$PY_VER" \
            -DPYTHON_SITE_PACKAGES="$PREFIX/lib/python$PY_VER/site-packages" \
            -DPython_INCLUDE_DIRS="$PREFIX/include/python$PY_VER" \
            -DPython_LIBRARY="$PREFIX/lib/libpython$PY_VER.a" \
            -DPython_LIBRARIES="$PREFIX/lib/libpython$PY_VER.a" \
            -DPython_Interpreter_FOUND=TRUE \
            -DPython_EXECUTABLE="$DEV_PREFIX/bin/python$PY_VER" \
            -DPYTHON_MODULE_EXTENSION=.so \
            -DPYTHON_MODULE_DEBUG_POSTFIX="" \
            -DPYTHON_MODULE_EXT_SUFFIX=.so \
            -DPython_FOUND=TRUE \
            -DWASM64="$([ "$ARCH" = "wasm64" ] && echo TRUE || echo FALSE)"
        emmake make -j"$NUM_JOBS"
        emmake make install
    )
    echo "pyjs ($ARCH): $BUILD_DIR/pyjs_runtime_browser.{js,wasm}, installed into $PREFIX"
}

# pack_runtime <env prefix> <out dir> [empack args...]: the runtime + the env
# packed by empack + the pyjs python module of this repository (as mount)
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

playwright_install() {
    # shellcheck disable=SC2086
    playwright install ${PLAYWRIGHT_INSTALL_ARGS:-} $BROWSERS
}

# run_in_browser <dir: tests|benchmarks> <backend> <browser> <host work dir> [args...]:
# <dir>/main.py with the runtime of the build dir and the pyjs module of the source tree
run_in_browser() {
    local dir="$1" backend="$2" browser="$3" workdir="$4"
    shift 4
    mkdir -p "$workdir"
    pyjs_code_runner run script "$backend" \
        --browser "$browser" \
        --conda-env "$DEPLOY_PREFIX" \
        --mount "$SRC_DIR/$dir:/$dir" \
        --mount "$SRC_DIR/module/pyjs:/lib/python$PY_VER/site-packages/pyjs" \
        --script main.py \
        --work-dir "/$dir" \
        --host-work-dir "$workdir" \
        --headless --no-cache --slow-mo 0 --async-main \
        --pyjs-dir "$BUILD_DIR" \
        "$@"
}

########################################
# commands
########################################
cmd_build() {
    use_arch "$ARCH"
    build_pyjs
}

cmd_test() {
    use_arch "$ARCH"
    build_pyjs
    create_env "$DEPLOY_PREFIX" "$PLATFORM" "${DEPLOY_SPECS[@]}"
    playwright_install
    # read by tests/main.py (mounted at /test_config)
    mkdir -p "$BUILD_DIR/test_config"
    printf '{"disable_jspi": %s}\n' "$([ "${DISABLE_JSPI:-0}" = "1" ] && echo true || echo false)" \
        > "$BUILD_DIR/test_config/config.json"
    local browser backend summary=() ret=0
    for browser in $BROWSERS; do
        for backend in $BACKENDS; do
            section "tests ($ARCH): $browser / $backend"
            if run_in_browser tests "$backend" "$browser" "$BUILD_DIR/host_work_dir_${browser}_$backend" \
                    --mount "$BUILD_DIR/test_config:/test_config"; then
                summary+=("  PASSED  $browser / $backend")
            else
                summary+=("  FAILED  $browser / $backend")
                ret=1
            fi
        done
    done
    printf '\ntest summary (%s, TEST_ENV=%s, DISABLE_JSPI=%s):\n' "$ARCH" "$TEST_ENV" "${DISABLE_JSPI:-0}"
    printf '%s\n' "${summary[@]}"
    return "$ret"
}

cmd_bench() {
    use_arch "$ARCH"
    build_pyjs
    create_env "$DEPLOY_PREFIX" "$PLATFORM" "${DEPLOY_SPECS[@]}"
    playwright_install
    local out="$BUILD_ROOT/benchmarks/$ARCH"
    mkdir -p "$BUILD_DIR/bench_config" "$out"
    # read by benchmarks/main.py (mounted at /bench_config)
    python -c 'import json, sys; json.dump({"filter": sys.argv[2]} if sys.argv[2] else {}, open(sys.argv[1], "w"))' \
        "$BUILD_DIR/bench_config/config.json" "${BENCH_FILTER:-}"
    local rev stamp browser backend name log ret=0
    rev="$(git -C "$SRC_DIR" rev-parse --short HEAD 2>/dev/null || echo unknown)"
    if [ -n "$(git -C "$SRC_DIR" status --porcelain --untracked-files=no 2>/dev/null)" ]; then rev="$rev-dirty"; fi
    stamp="$(date +%Y%m%d-%H%M%S)_$rev"
    for browser in $BROWSERS; do
        for backend in $BACKENDS; do
            section "benchmarks ($ARCH): $browser / $backend"
            name="${browser}_$backend"
            log="$out/${stamp}_$name.log"
            run_in_browser benchmarks "$backend" "$browser" "$BUILD_DIR/host_work_dir_bench_$name" \
                --mount "$BUILD_DIR/bench_config:/bench_config" 2>&1 | tee "$log" || ret=1
            # the result line of benchmarks/main.py (files written in the
            # browser do not reach the host) + build metadata
            if ! python - "$log" "$out/${stamp}_$name.json" "$ARCH" "$rev" "$stamp" "$backend" "$browser" <<'EOF'
import json, sys
log, out, wasm_type, git_rev, stamp, backend, browser = sys.argv[1:]
marker = "PYJS_BENCH_RESULT_JSON:"
lines = [l[l.find(marker) + len(marker):] for l in open(log) if marker in l]
if not lines:
    sys.exit(f"no benchmark results in {log}")
payload = json.loads(lines[-1])
payload["build"] = dict(wasm_type=wasm_type, git_rev=git_rev, timestamp=stamp, backend=backend, browser=browser)
json.dump(payload, open(out, "w"), indent=2)
EOF
            then
                ret=1
                continue
            fi
            ln -sf "$(basename "$log")" "$out/latest_$name.log"
            ln -sf "${stamp}_$name.json" "$out/latest_$name.json"
            echo "benchmark results: $out/${stamp}_$name.json"
        done
    done
    return "$ret"
}

# xeus-python from source against the pyjs in $PREFIX (the docs kernel); like
# the emscripten-forge recipe: python (+ its deps) linked statically
build_xeus_python() {
    local src="$BUILD_ROOT/src/xeus-python-$XEUS_PYTHON_REF" lib libs pkg
    for pkg in pyjs pyjs-dev libpyjs-static; do
        if compgen -G "$PREFIX/conda-meta/$pkg-[0-9]*.json" > /dev/null; then
            echo "$PREFIX contains the conda package $pkg: xeus-python would not be built against this pyjs"
            exit 1
        fi
    done
    if [ ! -d "$src" ]; then
        git clone --depth 1 --branch "$XEUS_PYTHON_REF" https://github.com/jupyter-xeus/xeus-python "$src"
    fi
    # the fake (native) pythons of the host env would be picked up by pybind11
    rm -f "$PREFIX"/bin/python*
    libs="$PREFIX/lib/libbz2.a;$PREFIX/lib/libz.a;$PREFIX/lib/libsqlite3.a;$PREFIX/lib/libffi.a"
    libs+=";$PREFIX/lib/libzstd.a;$PREFIX/lib/libssl.a;$PREFIX/lib/libcrypto.a;$PREFIX/lib/liblzma.a"
    for lib in expat mpdec Hacl_Hash_BLAKE2 Hacl_Hash_MD5 Hacl_Hash_SHA1 Hacl_Hash_SHA2 Hacl_Hash_SHA3; do
        libs+=";$PREFIX/lib/python$PY_VER/static/lib$lib.a"
    done
    libs+=";$PREFIX/lib/libpython$PY_VER.a"
    mkdir -p "$BUILD_ROOT/build_xeus_python_$ARCH"
    (
        cd "$BUILD_ROOT/build_xeus_python_$ARCH"
        # PYTHONLIBS_FOUND / PYTHON_*: pybind11 must not query the (native) build python
        emcmake cmake "${CMAKE_ARGS[@]}" "$src" -GNinja \
            -DCMAKE_FIND_ROOT_PATH_MODE_PACKAGE=ONLY \
            -DPYTHON_LIBRARIES="$libs" \
            -DPYBIND11_PYTHON_VERSION="$PY_VER" \
            -DPYTHONLIBS_FOUND=TRUE \
            -DPYTHON_MODULE_EXTENSION=.so \
            -DPYTHON_INCLUDE_DIR="$PREFIX/include/python$PY_VER" \
            -DPYTHON_INCLUDE_DIRS="$PREFIX/include/python$PY_VER"
        ninja
        ninja install
    )
    rm -rf "$PREFIX/share/jupyter/kernels/xpython-raw"
    echo "xeus-python $XEUS_PYTHON_REF ($ARCH) built against this pyjs, installed into $PREFIX"
}

# docs: per arch pyjs + xeus-python (the jupyterlite kernel) + the pyjs runtime
# for the javascript kernel, then sphinx (lite/ = wasm32) and a second,
# independent jupyterlite (lite64/ = wasm64)
cmd_docs() {
    local docs_extra="$BUILD_ROOT/docs_extra" arch
    # read by docs/conf.py
    export PYJS_DOCS_EXTRA_DIR="$docs_extra"
    unset PYJS_DOCS_KERNEL_PREFIX PYJS_DOCS_KERNEL_PREFIX_WASM64
    rm -rf "$docs_extra/pyjs-runtime"
    for arch in $ARCHS; do
        use_arch "$arch"
        build_pyjs
        build_xeus_python
        create_env "$DEPLOY_PREFIX" "$PLATFORM" "${DEPLOY_SPECS[@]}"
        pack_runtime "$DEPLOY_PREFIX" "$docs_extra/pyjs-runtime/$ARCH"
        if [ "$ARCH" = "wasm32" ]; then
            export PYJS_DOCS_KERNEL_PREFIX="$PREFIX"
        else
            export PYJS_DOCS_KERNEL_PREFIX_WASM64="$PREFIX"
        fi
    done

    rm -rf "$DOCS_OUT_DIR"
    sphinx-build -b html "$SRC_DIR/docs" "$DOCS_OUT_DIR"
    if [ -n "${PYJS_DOCS_KERNEL_PREFIX_WASM64:-}" ]; then
        # same notebooks, wasm64 kernel (config written by docs/conf.py); an
        # own lite dir: jupyterlite keeps its build state there
        local lite64="$BUILD_ROOT/lite64_dir" contents=() nb
        rm -rf "$lite64"
        mkdir -p "$lite64"
        for nb in "$SRC_DIR"/docs/_generated/notebooks/*.ipynb; do contents+=(--contents "$nb"); done
        (cd "$lite64" && jupyter lite build \
            --config "$SRC_DIR/docs/_generated/jupyter_lite_config_wasm64.json" \
            ${contents[@]+"${contents[@]}"} --output-dir "$DOCS_OUT_DIR/lite64" --lite-dir "$lite64")
    fi
    echo "docs: $DOCS_OUT_DIR/index.html"

    [ "$WITH_TESTS" = "1" ] || return 0
    playwright_install
    local browser ret=0
    for browser in $BROWSERS; do
        section "docs smoke test: $browser"
        python "$SRC_DIR/build_utils/docs_smoke_test.py" "$DOCS_OUT_DIR" --browser "$browser" || ret=1
    done
    return "$ret"
}

# npm package (npm/): per arch the runtime + python/stdlib/pyjs packed by
# empack, assembled into one package by npm/build.mjs
cmd_npm() {
    local arch stages=() entries=(index) version
    for arch in $ARCHS; do
        use_arch "$arch"
        build_pyjs
        create_env "$BUILD_ROOT/npm_env_prefix_$ARCH" "$PLATFORM" "${NPM_ENV_SPECS[@]}"
        # npm/empack_config.yaml drops CPython's test suite etc.
        pack_runtime "$BUILD_ROOT/npm_env_prefix_$ARCH" "$NPM_ROOT/stage/$ARCH" \
            --config "$SRC_DIR/npm/empack_config.yaml" --no-use-cache
        # channels + pinned python for mambajs (extra packages at runtime)
        python "$SRC_DIR/build_utils/npm_env_meta.py" "$NPM_ROOT/stage/$ARCH/empack_env_meta.json" \
            "${ENV_CHANNELS[@]}"
        stages+=(--stage "$ARCH=$NPM_ROOT/stage/$ARCH")
        entries+=("$ARCH")
    done

    version="$(sed -n 's/^project(pyjs VERSION \([0-9.]*\).*/\1/p' "$SRC_DIR/CMakeLists.txt")"
    local minify=()
    [ "${NPM_MINIFY:-1}" = "0" ] && minify=(--no-minify)
    (
        cd "$SRC_DIR/npm"
        npm ci --no-audit --no-fund
        node build.mjs --out "$NPM_ROOT/package" --name "$NPM_PACKAGE_NAME" --version "$version" \
            "${stages[@]}" ${minify[@]+"${minify[@]}"}
    )
    rm -f "$NPM_ROOT"/*.tgz
    (cd "$NPM_ROOT/package" && npm pack --pack-destination "$NPM_ROOT")
    local tgz
    tgz="$(ls "$NPM_ROOT"/*.tgz)"
    echo "npm package: $NPM_ROOT/package ($tgz)"
    echo "  publish:   cd $NPM_ROOT/package && npm publish --access public"

    [ "$WITH_TESTS" = "1" ] || return 0
    playwright_install
    local browser ret=0 network=()
    [ "${NPM_TEST_NETWORK:-1}" = "1" ] && network=(--network)
    for browser in $BROWSERS; do
        section "npm smoke test: $browser"
        python "$SRC_DIR/build_utils/npm_smoke_test.py" "$NPM_ROOT/package" --browser "$browser" \
            --entries "${entries[@]}" || ret=1
        if [ "${#network[@]}" -gt 0 ]; then
            python "$SRC_DIR/build_utils/npm_smoke_test.py" "$NPM_ROOT/package" --browser "$browser" \
                --entries "${entries[@]}" --network || ret=1
        fi
    done
    # the package in apps built with vite, webpack, rollup, esbuild, parcel
    # (the bundled output does not depend on the browser: one is enough)
    if [ "${NPM_TEST_BUNDLERS:-1}" = "1" ]; then
        section "npm bundler test"
        python "$SRC_DIR/build_utils/npm_bundler_test.py" "$tgz" \
            --browser "${BROWSERS%% *}" ${network[@]+"${network[@]}"} || ret=1
    fi
    return "$ret"
}

"cmd_$COMMAND"
