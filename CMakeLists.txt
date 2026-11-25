cmake_minimum_required(VERSION 4.0)
project(pyjs VERSION 6.0.0 DESCRIPTION "pyjs")

# What this builds:
#   pyjs                  libpyjs.a: the Python <-> JavaScript bridge. An
#                         embedder (e.g. xeus-python) links it into its own
#                         emscripten main module; nothing else is needed, the
#                         JavaScript part is inside the library.
#   pyjs_runtime_browser  a ready made main module: libpyjs + python + archive
#                         extraction (what the npm package ships).
# The host environment (python, the static libraries) is CMAKE_INSTALL_PREFIX.

##########################################################
# options
##########################################################
option(WASM64 "Enable WebAssembly 64-bit support" OFF)

# upper limit of the memory of the runtime (emscripten's default is 2GB, also
# for wasm64)
if(WASM64)
    set(PYJS_MAXIMUM_MEMORY "16GB" CACHE STRING "-sMAXIMUM_MEMORY of the pyjs runtime")
else()
    set(PYJS_MAXIMUM_MEMORY "4GB" CACHE STRING "-sMAXIMUM_MEMORY of the pyjs runtime")
endif()

# WebGPU (webgpu.h) via emscripten's emdawnwebgpu port, linked into every
# executable using pyjs: as MAIN_MODULE it carries the JS implementation for
# side modules
option(PYJS_WEBGPU "Enable WebGPU support (emdawnwebgpu port)" ON)

# OpenGL ES 3 / WebGL2 in the runtime (emscripten's GL JS library is always
# included in a MAIN_MODULE=1 runtime, but only at WebGL1 level without these
# flags)
option(PYJS_WEBGL "Enable WebGL2 / OpenGL ES 3 support in the runtime" ON)

# SDL2 (emscripten port) in the runtime: window / input / GL context for side
# modules like imgui-bundle's hello_imgui; must live in the main module
option(PYJS_SDL2 "Enable SDL2 support (emscripten sdl2 port) in the runtime" ON)

if(NOT DEFINED PY_VERSION)
    message(FATAL_ERROR "PY_VERSION is not set: pass the python version of the host environment, e.g. -DPY_VERSION=3.14")
endif()

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# the host environment pyjs is built against
set(HOST_PREFIX ${CMAKE_INSTALL_PREFIX})
set(PYTHON_INCLUDE_DIR ${HOST_PREFIX}/include/python${PY_VERSION})

##########################################################
# the JavaScript side (src/js/*.ts)
##########################################################
# esbuild bundles the TypeScript sources into one script, which is embedded
# into a C++ source of libpyjs (build_utils/embed_js.cmake explains how it
# gets from there into the runtime an embedder links)
find_program(ESBUILD esbuild REQUIRED)
file(GLOB PYJS_JS_SOURCES CONFIGURE_DEPENDS ${CMAKE_CURRENT_SOURCE_DIR}/src/js/*.ts)
add_custom_command(OUTPUT pyjs_js.cpp
    COMMAND ${ESBUILD} ${CMAKE_CURRENT_SOURCE_DIR}/src/js/index.ts
        --bundle --format=iife --target=es2022 --log-level=warning
        --outfile=${CMAKE_CURRENT_BINARY_DIR}/pyjs_bundle.js
    COMMAND ${CMAKE_COMMAND}
        -DIN=${CMAKE_CURRENT_BINARY_DIR}/pyjs_bundle.js
        -DOUT=${CMAKE_CURRENT_BINARY_DIR}/pyjs_js.cpp
        -P ${CMAKE_CURRENT_SOURCE_DIR}/build_utils/embed_js.cmake
    DEPENDS ${PYJS_JS_SOURCES} ${CMAKE_CURRENT_SOURCE_DIR}/build_utils/embed_js.cmake
)

##########################################################
# libpyjs
##########################################################
# nanobind (headers + sources, a noarch python package of the host env) is
# compiled into libpyjs: an embedder neither sees nor needs it
set(NANOBIND_DIR ${HOST_PREFIX}/lib/python${PY_VERSION}/site-packages/nanobind)

add_library(pyjs STATIC
    src/js_proxy.cpp
    src/deep.cpp
    src/py_entry.cpp
    src/module.cpp
    # several suspended Python stacks (JSPI), derived from pyodide: C, because
    # it uses CPython's internal headers
    src/stack_switching.c
    ${CMAKE_CURRENT_BINARY_DIR}/pyjs_js.cpp
    ${NANOBIND_DIR}/src/nb_combined.cpp
)
target_include_directories(pyjs PRIVATE
    ${PYTHON_INCLUDE_DIR}
    ${NANOBIND_DIR}/include
    ${NANOBIND_DIR}/ext/robin_map/include
)
target_compile_options(pyjs PRIVATE
    -fPIC
    -msimd128
    "SHELL: -fwasm-exceptions"
)
# what every executable linking pyjs must use too
target_link_options(pyjs PUBLIC "SHELL: -fwasm-exceptions")
if(WASM64)
    target_compile_options(pyjs PUBLIC -m64)
    target_link_options(pyjs PUBLIC -m64)
endif()
# INTERFACE: reaches every executable linking pyjs (the runtime below, and via
# the exported pyjsTargets.cmake e.g. xeus-python); the static lib itself does
# not use webgpu.h
if(PYJS_WEBGPU)
    target_link_options(pyjs INTERFACE "SHELL: --use-port=emdawnwebgpu")
endif()

##########################################################
# the runtime
##########################################################
# C libraries of optional extension modules: needed only if libpython has the
# module built in (older python builds). A newer python build has _sqlite3 /
# _ssl / _lzma as side modules in lib-dynload, each with its own static copy of
# the library. A second copy in the main module must not be linked then: the
# dynamic linker binds the side module's exported symbols (sqlite3_free, ...)
# to the main module's copy, whose global state the side module never
# initialized (sqlite: "null function" trap in sqlite3_close).
# (file(STRINGS) finds the name also in LTO bitcode: its string table is text)
#
# TODO: remove this block (and libsqlite-static / libopenssl-static /
# liblzma-static from the host dependencies) once the split python recipe
# (python-core + python-ssl / -sqlite3 / -lzma side modules) is merged into
# emscripten-forge: then no python that pyjs builds against has them built in.
set(PYTHON_OPTIONAL_LIBRARIES)
function(pyjs_link_if_builtin module)
    file(STRINGS ${HOST_PREFIX}/lib/libpython${PY_VERSION}.a found
         REGEX "PyInit_${module}" LIMIT_COUNT 1)
    if(found)
        foreach(lib ${ARGN})
            list(APPEND PYTHON_OPTIONAL_LIBRARIES ${HOST_PREFIX}/lib/${lib})
        endforeach()
        set(PYTHON_OPTIONAL_LIBRARIES ${PYTHON_OPTIONAL_LIBRARIES} PARENT_SCOPE)
    endif()
    message(STATUS "pyjs: ${module} built into libpython: ${found}")
endfunction()
pyjs_link_if_builtin(_sqlite3 libsqlite3.a)
pyjs_link_if_builtin(_lzma liblzma.a)
pyjs_link_if_builtin(_ssl libssl.a libcrypto.a)
pyjs_link_if_builtin(_hashlib libcrypto.a)
list(REMOVE_DUPLICATES PYTHON_OPTIONAL_LIBRARIES)

# what a python main module links (the static libraries of the host env)
set(PYTHON_LIBRARIES
    ${HOST_PREFIX}/lib/libbz2.a
    ${HOST_PREFIX}/lib/libz.a
    ${HOST_PREFIX}/lib/libffi.a
    ${HOST_PREFIX}/lib/libzstd.a
    ${PYTHON_OPTIONAL_LIBRARIES}
    ${HOST_PREFIX}/lib/libpython${PY_VERSION}.a
    ${HOST_PREFIX}/lib/python${PY_VERSION}/static/libexpat.a
    ${HOST_PREFIX}/lib/python${PY_VERSION}/static/libmpdec.a
    ${HOST_PREFIX}/lib/python${PY_VERSION}/static/libHacl_Hash_BLAKE2.a
    ${HOST_PREFIX}/lib/python${PY_VERSION}/static/libHacl_Hash_MD5.a
    ${HOST_PREFIX}/lib/python${PY_VERSION}/static/libHacl_Hash_SHA1.a
    ${HOST_PREFIX}/lib/python${PY_VERSION}/static/libHacl_Hash_SHA2.a
    ${HOST_PREFIX}/lib/python${PY_VERSION}/static/libHacl_Hash_SHA3.a
)

# src/extract.cpp (archive extraction with libarchive) only here, not in
# libpyjs: embedders like xeus-python fill the file system themselves
add_executable(pyjs_runtime_browser src/extract.cpp)
# (archive.h of libarchive)
target_include_directories(pyjs_runtime_browser PRIVATE ${HOST_PREFIX}/include)
target_compile_options(pyjs_runtime_browser PRIVATE
    -fPIC
    -msimd128
    "SHELL: -fwasm-exceptions"
)
# libarchive first: it needs bz2 / z / zstd from PYTHON_LIBRARIES
target_link_libraries(pyjs_runtime_browser PRIVATE
    ${HOST_PREFIX}/lib/libarchive.a
    ${PYTHON_LIBRARIES}
    pyjs
)
target_link_options(pyjs_runtime_browser PRIVATE
    # a main module: python extension modules are loaded as side modules
    "SHELL: -s MAIN_MODULE=1"
    "SHELL: -s EXPORT_ALL=1"
    # the runtime is created by calling createModule(...)
    "SHELL: -s MODULARIZE=1"
    "SHELL: -s EXPORT_NAME=\"createModule\""
    "SHELL: -s ENVIRONMENT=web,worker"
    "SHELL: -s ALLOW_MEMORY_GROWTH=1"
    "SHELL: -s MAXIMUM_MEMORY=${PYJS_MAXIMUM_MEMORY}"
    "SHELL: -s INITIAL_MEMORY=64MB"
    "SHELL: -s STACK_SIZE=32mb"
    "SHELL: -s FORCE_FILESYSTEM"
    "SHELL: -sSUPPORT_LONGJMP"
    # src/extract.cpp uses embind
    "SHELL: -lembind"
)
# graphics only in the runtime (not INTERFACE on pyjs: downstream executables
# like xeus-python are not forced to link them)
if(PYJS_WEBGL)
    target_link_options(pyjs_runtime_browser PRIVATE
        "SHELL: -lGL"
        "SHELL: -sMAX_WEBGL_VERSION=2"
        "SHELL: -sFULL_ES3"
    )
endif()
if(PYJS_SDL2)
    target_link_options(pyjs_runtime_browser PRIVATE "SHELL: -sUSE_SDL=2")
endif()

##########################################################
# install
##########################################################
include(GNUInstallDirs)
include(CMakePackageConfigHelpers)

set(PYJS_CMAKECONFIG_INSTALL_DIR "${CMAKE_INSTALL_LIBDIR}/cmake/${PROJECT_NAME}" CACHE STRING "install path for pyjsConfig.cmake")

# the runtime (js + wasm)
install(TARGETS pyjs_runtime_browser DESTINATION ${HOST_PREFIX}/lib_js/pyjs)
install(FILES "$<TARGET_FILE_DIR:pyjs_runtime_browser>/pyjs_runtime_browser.wasm"
        DESTINATION ${HOST_PREFIX}/lib_js/pyjs)

# libpyjs + `find_package(pyjs)`: target pyjs
install(TARGETS pyjs EXPORT pyjs-targets ARCHIVE DESTINATION ${CMAKE_INSTALL_LIBDIR})
install(EXPORT pyjs-targets FILE pyjsTargets.cmake DESTINATION ${PYJS_CMAKECONFIG_INSTALL_DIR})
# (also usable from the build tree)
export(EXPORT pyjs-targets FILE "${CMAKE_CURRENT_BINARY_DIR}/pyjsTargets.cmake")
configure_package_config_file(pyjsConfig.cmake.in
                              "${CMAKE_CURRENT_BINARY_DIR}/pyjsConfig.cmake"
                              INSTALL_DESTINATION ${PYJS_CMAKECONFIG_INSTALL_DIR})
write_basic_package_version_file(${CMAKE_CURRENT_BINARY_DIR}/pyjsConfigVersion.cmake
                                 VERSION ${pyjs_VERSION}
                                 COMPATIBILITY AnyNewerVersion)
install(FILES ${CMAKE_CURRENT_BINARY_DIR}/pyjsConfig.cmake
              ${CMAKE_CURRENT_BINARY_DIR}/pyjsConfigVersion.cmake
        DESTINATION ${PYJS_CMAKECONFIG_INSTALL_DIR})

# the python package
install(DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}/module/pyjs
        DESTINATION ${HOST_PREFIX}/lib/python${PY_VERSION}/site-packages
        FILES_MATCHING PATTERN "*.py"
        PATTERN "__pycache__" EXCLUDE
)
