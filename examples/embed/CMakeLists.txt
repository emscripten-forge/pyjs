cmake_minimum_required(VERSION 3.20)
project(pyjs_embed_example CXX)

# A program embedding pyjs: libpyjs + libpython linked into one executable,
# the python standard library put into its file system by emscripten's file
# packager. run.js starts python and runs code.
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
    # pyjs requires a main module: it keeps all of libpyjs (nothing in the
    # program itself calls into it, python is started from JavaScript) and the
    # parts of the emscripten runtime pyjs' JavaScript uses; and python
    # extension modules are loaded as side modules
    "SHELL: -s MAIN_MODULE=1"
    # run.js creates the program with createModule(...)
    "SHELL: -s MODULARIZE=1"
    "SHELL: -s EXPORT_NAME=createModule"
    "SHELL: -s ENVIRONMENT=node"
    "SHELL: -s ALLOW_MEMORY_GROWTH=1"
    "SHELL: -s STACK_SIZE=32mb"
    "SHELL: -s FORCE_FILESYSTEM"
    "SHELL: -s SUPPORT_LONGJMP"
    # The file system: the standard library to /lib/pythonX.Y (where
    # startPython() expects it), the python package of pyjs to its
    # site-packages (python imports it when it starts; here from the
    # repository, normally it is in the host environment's site-packages
    # already, which would then not be excluded below). Packed into
    # embed.data, loaded before createModule() resolves. Not packed: the
    # bytecode caches, CPython's test suite (most of the size), the packages
    # of the host environment, and lib-dynload (the shared libraries of the
    # optional stdlib modules: a program needing them loads them itself, see
    # docs/cpp.md).
    "SHELL: --preload-file ${PYTHON_LIB_DIR}@/lib/python${PY_VERSION}"
    # (outside of the pyjs repository: drop this line and the exclusion of
    # site-packages below, pyjs-dev put the module into the host environment's
    # site-packages)
    "SHELL: --preload-file ${CMAKE_CURRENT_SOURCE_DIR}/../../module/pyjs@/lib/python${PY_VERSION}/site-packages/pyjs"
    "SHELL: --exclude-file */__pycache__"
    "SHELL: --exclude-file ${PYTHON_LIB_DIR}/test"
    "SHELL: --exclude-file ${PYTHON_LIB_DIR}/site-packages"
    "SHELL: --exclude-file ${PYTHON_LIB_DIR}/lib-dynload"
    "SHELL: --exclude-file ${PYTHON_LIB_DIR}/static"
)
