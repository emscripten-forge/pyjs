cmake_minimum_required(VERSION 3.20)
project(pyjs_embed_example CXX)

# A C++ program embedding python (pybind11) and pyjs: libpyjs + libpython
# linked into one executable, the python standard library put into its file
# system by emscripten's file packager. main.cpp sets up everything (no
# JavaScript of its own): `node build/<arch>/embed.js`.
#
#   HOST_PREFIX   the emscripten environment (python + static libraries)
#   PY_VERSION    its python version, e.g. 3.14
#   WASM_ARCH     wasm32 | wasm64
#   pyjs_DIR      where pyjsConfig.cmake is. Default: the build tree of this
#                 repository (`pixi run build <arch>` in the root).
#
# Normally pyjs comes from emscripten-forge: `pyjs-dev` in the host
# environment (pixi.toml), find_package(pyjs) finds it there without pyjs_DIR,
# and the python module `pyjs` is in the host environment's site-packages.
# This example tests the pyjs of this repository, so it takes both from the
# repository (README.md).

# Outside of the pyjs repository, use this instead of the block below (pyjs-dev
# in the host environment):
#   list(APPEND CMAKE_PREFIX_PATH ${HOST_PREFIX})
#   find_package(pyjs REQUIRED)
if(NOT pyjs_DIR)
    set(pyjs_DIR ${CMAKE_CURRENT_SOURCE_DIR}/../../build_root/build_${WASM_ARCH})
endif()
find_package(pyjs REQUIRED)

add_executable(embed main.cpp)

# Where python lives in the program's file system (its prefix, the argument
# of pyjs_initialize in main.cpp): any directory works, here not "/" (the
# default) on purpose, to show and test that
set(EMBED_PYTHON_HOME "/python")
target_compile_definitions(embed PRIVATE EMBED_PYTHON_HOME="${EMBED_PYTHON_HOME}")
# python's headers and pybind11's (header only), both in the host environment
target_include_directories(embed PRIVATE
    ${HOST_PREFIX}/include
    ${HOST_PREFIX}/include/python${PY_VERSION}
)

# libpython and what it needs. The C libraries of _sqlite3 / _ssl / _lzma only
# if the host environment has them: a python with these modules built in
# needs them; with the split python recipe (python-sqlite3, ... as side
# modules) libpython-static does not bring them.
set(PYTHON_LIB_DIR ${HOST_PREFIX}/lib/python${PY_VERSION})
set(PYTHON_LIBRARIES)
foreach(lib libsqlite3.a liblzma.a libssl.a libcrypto.a)
    if(EXISTS ${HOST_PREFIX}/lib/${lib})
        list(APPEND PYTHON_LIBRARIES ${HOST_PREFIX}/lib/${lib})
    endif()
endforeach()
target_link_libraries(embed PRIVATE
    pyjs
    ${PYTHON_LIBRARIES}
    ${HOST_PREFIX}/lib/libpython${PY_VERSION}.a
    ${HOST_PREFIX}/lib/libbz2.a
    ${HOST_PREFIX}/lib/libz.a
    ${HOST_PREFIX}/lib/libffi.a
    ${HOST_PREFIX}/lib/libzstd.a
    ${PYTHON_LIB_DIR}/static/libexpat.a
    ${PYTHON_LIB_DIR}/static/libmpdec.a
    ${PYTHON_LIB_DIR}/static/libHacl_Hash_BLAKE2.a
    ${PYTHON_LIB_DIR}/static/libHacl_Hash_MD5.a
    ${PYTHON_LIB_DIR}/static/libHacl_Hash_SHA1.a
    ${PYTHON_LIB_DIR}/static/libHacl_Hash_SHA2.a
    ${PYTHON_LIB_DIR}/static/libHacl_Hash_SHA3.a
)

# (-fwasm-exceptions, and -m64 for wasm64, come with the pyjs target)
target_link_options(embed PRIVATE
    # pyjs requires a main module: it keeps all of libpyjs and the parts of
    # the emscripten runtime pyjs' JavaScript uses; and python extension
    # modules are loaded as side modules
    "SHELL: -s MAIN_MODULE=1"
    # a plain node program: `node embed.js` runs main (a web page would
    # rather use MODULARIZE + createModule())
    "SHELL: -s ENVIRONMENT=node"
    "SHELL: -s ALLOW_MEMORY_GROWTH=1"
    "SHELL: -s STACK_SIZE=32mb"
    "SHELL: -s FORCE_FILESYSTEM"
    "SHELL: -s SUPPORT_LONGJMP"
    # The file system, under python's prefix EMBED_PYTHON_HOME: the standard
    # library + site-packages (numpy, ...) to <prefix>/lib/pythonX.Y, the
    # shared libraries of the packages (libopenblas.so, which numpy's
    # extension modules need) to <prefix>/lib. --embed-file: packed into the
    # wasm itself (no separate .data file to locate; --preload-file would
    # load an embed.data, which node looks for in the current directory), in
    # the file system before main runs. Not packed: the bytecode caches,
    # CPython's test suite (most of the size), the static libraries.
    "SHELL: --embed-file ${PYTHON_LIB_DIR}@${EMBED_PYTHON_HOME}/lib/python${PY_VERSION}"
    "SHELL: --embed-file ${HOST_PREFIX}/lib/libopenblas.so@${EMBED_PYTHON_HOME}/lib/libopenblas.so"
    # the python package pyjs, from the repository (outside of the pyjs
    # repository: drop this line, pyjs-dev put the module into the host
    # environment's site-packages, packed with it above)
    "SHELL: --embed-file ${CMAKE_CURRENT_SOURCE_DIR}/../../module/pyjs@${EMBED_PYTHON_HOME}/lib/python${PY_VERSION}/site-packages/pyjs"
    "SHELL: --exclude-file */__pycache__"
    "SHELL: --exclude-file ${PYTHON_LIB_DIR}/test"
    "SHELL: --exclude-file ${PYTHON_LIB_DIR}/static"
)
