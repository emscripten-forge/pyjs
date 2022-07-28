cmake_minimum_required(VERSION 3.9)
project(pyjs VERSION 0.7.0 DESCRIPTION "pyjs")

option(BUILD_RUNNER "Build runner" OFF)

set(PYCPPSCRIPTS
    convert.py
    core.py
    error_handling.py
    extend_js_val.py
    webloop.py
)

file(MAKE_DIRECTORY ${CMAKE_CURRENT_BINARY_DIR}/pycpp_includes)
foreach(script ${PYCPPSCRIPTS})
    string(REPLACE "." "_" script_var ${script})
    add_custom_command(OUTPUT pycpp_includes/${script}.hpp
                       DEPENDS include/pyjs/pycpp/${script}
                       COMMAND $ENV{CONDA_PREFIX}/bin/python ${CMAKE_SOURCE_DIR}/embed_pycpp.py
                        ${CMAKE_CURRENT_SOURCE_DIR}/include/pyjs/pycpp/${script}
                        ${CMAKE_CURRENT_BINARY_DIR}/pycpp_includes/${script}.hpp)
endforeach()

set(PYJS_HEADERS
    include/pyjs/convert.hpp
    include/pyjs/export_js_module.hpp
    include/pyjs/export_js_proxy.hpp
    include/pyjs/export_py_object.hpp
    include/pyjs/export_pyjs_module.hpp
    include/pyjs/macro_magic.hpp
    pre.js
)

set(PYCPPSOURCES "")
foreach(script ${PYCPPSCRIPTS})
    list(APPEND PYCPPSOURCES pycpp_includes/${script}.hpp)
endforeach()


set(CMAKE_CXX_STANDARD 14)
set(CMAKE_CXX_STANDARD_REQUIRED ON)


set(pybind11_REQUIRED_VERSION 2.6.1)

if (NOT TARGET pybind11::headers)
    find_package(pybind11 ${pybind11_REQUIRED_VERSION} REQUIRED)
endif ()



configure_file(pre.js  ${CMAKE_CURRENT_BINARY_DIR}/pre.js  COPYONLY)
configure_file(post.js ${CMAKE_CURRENT_BINARY_DIR}/post.js COPYONLY)

set(EM_FLAGS "${EM_FLAGS} -s WASM=1 --bind --pre-js pre.js")

add_library(pyjs INTERFACE)

set_target_properties(pyjs PROPERTIES
    PUBLIC_HEADER "${PYJS_HEADERS}"
)

target_link_libraries(pyjs INTERFACE pybind11::pybind11)
target_compile_options(pyjs INTERFACE -fPIC)

target_include_directories(pyjs
                           INTERFACE
                           $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
                           $<BUILD_INTERFACE:${CMAKE_CURRENT_BINARY_DIR}>
                           $<INSTALL_INTERFACE:include>)

SET(PYTHON_UTIL_LIBS
    ${CMAKE_INSTALL_PREFIX}/lib/libbz2.a
    ${CMAKE_INSTALL_PREFIX}/lib/libz.a
    ${CMAKE_INSTALL_PREFIX}/lib/libsqlite3.a
    ${CMAKE_INSTALL_PREFIX}/lib/libffi.a
)

if(BUILD_RUNNER)
    add_executable(pyjs_main src/main.cpp ${PYCPPSOURCES})
    set_target_properties(pyjs_main
        PROPERTIES
            CXX_STANDARD 17
    )
    target_compile_definitions(pyjs_main PUBLIC -DPYJS_WEB)
    target_compile_options(pyjs_main PRIVATE -fPIC)
    target_link_libraries(pyjs_main PUBLIC pyjs)
    target_link_libraries(pyjs_main PRIVATE ${PYTHON_UTIL_LIBS} pybind11::embed pyjs)

    target_compile_options(pyjs_main
        PUBLIC --std=c++17
        PUBLIC -Wno-deprecated
        PUBLIC "SHELL: --bind"
        PUBLIC "SHELL: -s ENVIRONMENT=worker"
        PUBLIC "SHELL: -fwasm-exceptions"
        PUBLIC "SHELL: -s FORCE_FILESYSTEM"
        PUBLIC "SHELL: -s LZ4=1"
        PUBLIC "SHELL: -flto"
    )

    target_link_options(pyjs_main
        PUBLIC --bind
        PUBLIC -Wno-unused-command-line-argument
        PUBLIC "SHELL: --bind"
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
        PUBLIC "SHELL: -fwasm-exceptions"
        PUBLIC "SHELL: -s MAIN_MODULE=1"
        PUBLIC "SHELL: -s ENVIRONMENT=worker"
        PUBLIC "SHELL: -s TOTAL_STACK=512mb"
        PUBLIC "SHELL: -s INITIAL_MEMORY=1024mb"
        PUBLIC "SHELL: -s FORCE_FILESYSTEM"
        PUBLIC "SHELL: -s LZ4=1"
        PUBLIC "SHELL: --post-js post.js"
        PUBLIC "SHELL: --pre-js pre.js"
        PUBLIC "SHELL: -flto"
    )
endif()

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
