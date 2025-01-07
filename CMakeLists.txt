cmake_minimum_required(VERSION 3.9)

project(pyjs VERSION 2.4.0 DESCRIPTION "pyjs")

option(BUILD_RUNTIME_BROWSER "Build runtime" ON)
option(WITH_NODE_TESTS "With node tests" OFF)
option(LINK_LIBEXPAT "Link libexpat" OFF)
option(LINK_LIBMPDEC "Link libmpdec" OFF)

# set PY_VERSION to 3.11 if the user has not set it
if (NOT DEFINED PY_VERSION)
    set(PY_VERSION 3.11)
endif()


file(MAKE_DIRECTORY ${CMAKE_CURRENT_BINARY_DIR}/pycpp_includes)




##########################################################
# generate prejs and postjs
##########################################################
set(PREJS_FILES
    ${CMAKE_CURRENT_SOURCE_DIR}/include/pyjs/pre_js/constants.js
    ${CMAKE_CURRENT_SOURCE_DIR}/include/pyjs/pre_js/get_type_string.js
    ${CMAKE_CURRENT_SOURCE_DIR}/include/pyjs/pre_js/wrap_result.js
    ${CMAKE_CURRENT_SOURCE_DIR}/include/pyjs/pre_js/apply.js
    ${CMAKE_CURRENT_SOURCE_DIR}/include/pyjs/pre_js/get_set_attr.js
    ${CMAKE_CURRENT_SOURCE_DIR}/include/pyjs/pre_js/promise.js
    ${CMAKE_CURRENT_SOURCE_DIR}/include/pyjs/pre_js/create_once_callable.js
    ${CMAKE_CURRENT_SOURCE_DIR}/include/pyjs/pre_js/shortcuts.js
    ${CMAKE_CURRENT_SOURCE_DIR}/include/pyjs/pre_js/operators.js
    ${CMAKE_CURRENT_SOURCE_DIR}/include/pyjs/pre_js/platform.js
    ${CMAKE_CURRENT_SOURCE_DIR}/include/pyjs/pre_js/wait_for_dependencies.js
    ${CMAKE_CURRENT_SOURCE_DIR}/include/pyjs/pre_js/init.js
    ${CMAKE_CURRENT_SOURCE_DIR}/include/pyjs/pre_js/cleanup.js
    ${CMAKE_CURRENT_SOURCE_DIR}/include/pyjs/pre_js/make_proxy.js
    ${CMAKE_CURRENT_SOURCE_DIR}/include/pyjs/pre_js/dynload/dynload.js
    ${CMAKE_CURRENT_SOURCE_DIR}/include/pyjs/pre_js/fetch.js
    ${CMAKE_CURRENT_SOURCE_DIR}/include/pyjs/pre_js/load_pkg.js
)
set(POSTJS_FILES
    ${CMAKE_CURRENT_SOURCE_DIR}/include/pyjs/post_js/fixes.js
)


add_custom_target(merge_pyjs ALL
    DEPENDS
        "pyjs_pre.js"
        "pyjs_post.js"
    )


add_custom_command(OUTPUT "pyjs_pre.js"
    COMMAND $ENV{CONDA_PREFIX}/bin/python
        ${CMAKE_SOURCE_DIR}/build_utils/merge_js.py
        ${PREJS_FILES}
        pyjs_pre.js
        ${CMAKE_CURRENT_SOURCE_DIR}/src/js_timestamp.cpp
    DEPENDS ${PREJS_FILES}
)

add_custom_command(OUTPUT "pyjs_post.js"
    COMMAND $ENV{CONDA_PREFIX}/bin/python
        ${CMAKE_SOURCE_DIR}/build_utils/merge_js.py
        ${POSTJS_FILES}
        pyjs_post.js
        ${CMAKE_CURRENT_SOURCE_DIR}/src/js_timestamp.cpp
    DEPENDS  ${POSTJS_FILES})





##########################################################
# headers to install
##########################################################
set(PYJS_HEADERS
    include/pyjs/convert.hpp
    include/pyjs/export_js_module.hpp
    include/pyjs/export_js_proxy.hpp
    include/pyjs/export_py_object.hpp
    include/pyjs/export_pyjs_module.hpp
    include/pyjs/untar.hpp
    include/pyjs/install_conda_file.hpp
    include/pyjs/inflate.hpp
    ${CMAKE_CURRENT_BINARY_DIR}/pyjs_pre.js
    ${CMAKE_CURRENT_BINARY_DIR}/pyjs_post.js
)



set(CMAKE_CXX_STANDARD 14)
set(CMAKE_CXX_STANDARD_REQUIRED ON)


set(pybind11_REQUIRED_VERSION 2.6.1)

if (NOT TARGET pybind11::headers)
    find_package(pybind11 ${pybind11_REQUIRED_VERSION} REQUIRED)
endif ()


add_library(pyjs STATIC
    src/export_js_module.cpp
    src/export_js_proxy.cpp
    src/export_py_object.cpp
    src/convert.cpp
    src/export_pyjs_module.cpp
    src/js_timestamp.cpp
    src/inflate.cpp
    src/untar.cpp
    src/install_conda_file.cpp
    ${PYCPPSOURCES}
)

target_link_libraries(pyjs PRIVATE ${PYTHON_UTIL_LIBS} pybind11::embed)


target_compile_options(pyjs
    PUBLIC --std=c++17
    PUBLIC -Wno-deprecated
    PUBLIC "SHELL: -fexceptions"
)

target_link_options(pyjs
    PRIVATE -lembind
    PUBLIC -Wno-unused-command-line-argument
    PUBLIC "SHELL: -fexceptions"
    #PUBLIC "SHELL:-s EXPORT_EXCEPTION_HANDLING_HELPERS"
    #PUBLIC "SHELL:-s EXCEPTION_CATCHING_ALLOWED=['we only want to allow exception handling in side modules']"
)



set_target_properties(pyjs PROPERTIES
    PUBLIC_HEADER "${PYJS_HEADERS}"
    # DEPENDS "pyjs_pre.js" "pyjs_post.js"
)

add_dependencies(pyjs merge_pyjs)

target_link_libraries(pyjs PRIVATE pybind11::pybind11)
target_compile_options(pyjs PRIVATE -fPIC)


SET(BUILD_INCLUDES ${CMAKE_CURRENT_SOURCE_DIR}/include
)

target_include_directories(pyjs
                           PUBLIC
                            $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
                            $<INSTALL_INTERFACE:include>  # <prefix>/include
)

SET(PYTHON_UTIL_LIBS
    ${CMAKE_INSTALL_PREFIX}/lib/libbz2.a
    ${CMAKE_INSTALL_PREFIX}/lib/libz.a
    ${CMAKE_INSTALL_PREFIX}/lib/libsqlite3.a
    ${CMAKE_INSTALL_PREFIX}/lib/libffi.a
    ${CMAKE_INSTALL_PREFIX}/lib/libzstd.a
)


if (LINK_LIBEXPAT)
    SET(PYTHON_UTIL_LIBS ${PYTHON_UTIL_LIBS} ${CMAKE_INSTALL_PREFIX}/lib/libexpat.a)
endif()

if (LINK_LIBMPDEC)
    SET(PYTHON_UTIL_LIBS ${PYTHON_UTIL_LIBS} ${CMAKE_INSTALL_PREFIX}/lib/libmpdec.a)
endif()

set_target_properties(pyjs
    PROPERTIES
    CXX_STANDARD 17
)


add_executable(pyjs_runtime_browser src/runtime.cpp )
SET(ENVIRONMENT "web,worker")
target_compile_definitions(pyjs_runtime_browser PUBLIC -DPYTEST_DRIVER_WEB)

target_include_directories(pyjs_runtime_browser
                        PRIVATE
                        ${CMAKE_SOURCE_DIR}/include
                        ${CMAKE_CURRENT_BINARY_DIR}/pycpp_includes
                        ${ZLIB_INCLUDE_DIRS}
                    )

set_target_properties(pyjs_runtime_browser
    PROPERTIES
        CXX_STANDARD 17
)
target_compile_definitions(pyjs_runtime_browser PUBLIC -DPYJS_WEB)
target_compile_options(pyjs_runtime_browser PRIVATE -fPIC)
target_link_libraries(pyjs_runtime_browser PRIVATE pyjs  pybind11::embed ${PYTHON_UTIL_LIBS})



target_compile_options(pyjs_runtime_browser
    PUBLIC --std=c++17
    PUBLIC -Wno-deprecated
    PUBLIC "SHELL: -s ENVIRONMENT=${ENVIRONMENT}"
    PUBLIC "SHELL: -fexceptions"
    #PUBLIC "SHELL:-s EXPORT_EXCEPTION_HANDLING_HELPERS"
    PUBLIC "SHELL: -s FORCE_FILESYSTEM"
    PUBLIC "SHELL: -s LZ4=1"
    PUBLIC "SHELL: -flto"
    # PUBLIC "SHELL: -s WASM_BIGINT"
)

target_link_options(pyjs_runtime_browser
    PRIVATE -lembind
    PUBLIC -Wno-unused-command-line-argument
    PUBLIC "SHELL: -s MODULARIZE=1"
    PUBLIC "SHELL: -s EXPORT_NAME=\"createModule\""
    PUBLIC "SHELL: -s EXPORT_ES6=0"
    PUBLIC "SHELL: -s USE_ES6_IMPORT_META=0"
    PUBLIC "SHELL: -s DEMANGLE_SUPPORT=0"
    PUBLIC "SHELL: -s ASSERTIONS=0"
    PUBLIC "SHELL: -s ALLOW_MEMORY_GROWTH=1"
    PUBLIC "SHELL: -s EXIT_RUNTIME=1"
    PUBLIC "SHELL: -s WASM=1"
    PUBLIC "SHELL: -s USE_PTHREADS=0"
    PUBLIC "SHELL: -s ENVIRONMENT=${ENVIRONMENT}"
    PUBLIC "SHELL: -fexceptions"
    PUBLIC "SHELL: -s MAIN_MODULE=1"
    PUBLIC "SHELL: -s ENVIRONMENT=${ENVIRONMENT}"
    PUBLIC "SHELL: -s TOTAL_STACK=16mb"
    PUBLIC "SHELL: -s INITIAL_MEMORY=64mb"
    PUBLIC "SHELL: -s FORCE_FILESYSTEM"
    PUBLIC "SHELL: -s LZ4=1"
    PUBLIC "SHELL: --post-js pyjs_post.js"
    PUBLIC "SHELL: --pre-js pyjs_pre.js"
    PUBLIC "SHELL: -flto"
    PUBLIC "SHELL: -lidbfs.js"
    PUBLIC "SHELL: -s WASM_BIGINT"
)


install(TARGETS pyjs_runtime_browser
        DESTINATION ${CMAKE_INSTALL_PREFIX}/lib_js/pyjs)
install(FILES
        "$<TARGET_FILE_DIR:pyjs_runtime_browser>/pyjs_runtime_browser.wasm"
        DESTINATION ${CMAKE_INSTALL_PREFIX}/lib_js/pyjs)





include(GNUInstallDirs)
include(CMakePackageConfigHelpers)

set(PYJS_CMAKECONFIG_INSTALL_DIR "${CMAKE_INSTALL_LIBDIR}/cmake/${PROJECT_NAME}" CACHE STRING "install path for pyjsConfig.cmake")

# Configure 'pyjsConfig.cmake' for an install tree
set(PYJS_CONFIG_CODE "")

# Configure 'pyjs-pythonConfig.cmake' for a build tree
set(PYJS_CONFIG_CODE "####### Expanded from \@PYJS_CONFIG_CODE\@ #######\n")
set(PYJS_CONFIG_CODE "${PYJS_CONFIG_CODE}set(CMAKE_MODULE_PATH \"${CMAKE_CURRENT_SOURCE_DIR}/cmake;\${CMAKE_MODULE_PATH}\")\n")
set(PYJS_CONFIG_CODE "${PYJS_CONFIG_CODE}##################################################")
configure_package_config_file(${PROJECT_NAME}Config.cmake.in
                              "${CMAKE_CURRENT_BINARY_DIR}/${PROJECT_NAME}Config.cmake"
                              INSTALL_DESTINATION ${PROJECT_BINARY_DIR})

# Configure 'pyjs-pythonConfig.cmake' for an install tree
set(PYJS_CONFIG_CODE "")

configure_package_config_file(${PROJECT_NAME}Config.cmake.in
                              "${CMAKE_CURRENT_BINARY_DIR}/CMakeFiles/${PROJECT_NAME}Config.cmake"
                              INSTALL_DESTINATION ${PYJS_CMAKECONFIG_INSTALL_DIR})


write_basic_package_version_file(${CMAKE_CURRENT_BINARY_DIR}/${PROJECT_NAME}ConfigVersion.cmake
                                 VERSION ${${PROJECT_NAME}_VERSION}
                                 COMPATIBILITY AnyNewerVersion)
install(FILES ${CMAKE_CURRENT_BINARY_DIR}/CMakeFiles/${PROJECT_NAME}Config.cmake
              ${CMAKE_CURRENT_BINARY_DIR}/${PROJECT_NAME}ConfigVersion.cmake
              DESTINATION ${PYJS_CMAKECONFIG_INSTALL_DIR})

# export(EXPORT ${PROJECT_NAME}-targets
#        FILE "${CMAKE_CURRENT_BINARY_DIR}/${PROJECT_NAME}Targets.cmake")

set(PYJS_PYTHON_TARGETS "")
list(APPEND PYJS_PYTHON_TARGETS pyjs)

install(TARGETS ${PYJS_PYTHON_TARGETS}
        EXPORT pyjs-targets
        ARCHIVE DESTINATION ${CMAKE_INSTALL_LIBDIR}
        LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR}
        RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR}
        PUBLIC_HEADER DESTINATION ${CMAKE_INSTALL_INCLUDEDIR}/pyjs)

export(EXPORT ${PROJECT_NAME}-targets
           FILE "${CMAKE_CURRENT_BINARY_DIR}/${PROJECT_NAME}Targets.cmake")

install(EXPORT ${PROJECT_NAME}-targets
            FILE ${PROJECT_NAME}Targets.cmake
            DESTINATION ${PYJS_CMAKECONFIG_INSTALL_DIR})



install(DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}/module/pyjs
        DESTINATION ${CMAKE_INSTALL_PREFIX}/lib/python${PY_VERSION}/site-packages
        FILES_MATCHING PATTERN "*.py"
        PATTERN "__pycache__" EXCLUDE
)
