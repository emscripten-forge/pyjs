cmake_minimum_required(VERSION 3.9)
project(pyjs VERSION 0.10.0 DESCRIPTION "pyjs")

option(BUILD_RUNTIME_BROWSER "Build runtime" ON)
option(BUILD_RUNTIME_NODE "Build runtime" ON)
option(WITH_NODE_TESTS "With node tests" ON)



##########################################################
# embed python files in C++ headers
##########################################################
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
    add_custom_command(OUTPUT pycpp_includes/${script}.cpp
                       DEPENDS include/pyjs/pycpp/${script}
                       COMMAND $ENV{CONDA_PREFIX}/bin/python ${CMAKE_SOURCE_DIR}/embed_pycpp.py
                        ${CMAKE_CURRENT_SOURCE_DIR}/include/pyjs/pycpp/${script}
                        ${CMAKE_CURRENT_BINARY_DIR}/pycpp_includes/${script}.cpp)
endforeach()





    # add_custom_target( copy_pre_js
    #                     DEPENDS ${CMAKE_SOURCE_DIR}/pre.js
    #                     COMMAND ${CMAKE_COMMAND} -E copy_if_different
    #                    ${CMAKE_SOURCE_DIR}/pre.js
    #                    ${CMAKE_BINARY_DIR}/pre.js
    #                     COMMENT "Copying 'pre.js' library to bin")


ADD_CUSTOM_COMMAND(OUTPUT  ${CMAKE_BINARY_DIR}/pre.js
  COMMAND ${CMAKE_COMMAND} -E copy_if_different
                       ${CMAKE_SOURCE_DIR}/pre.js
                       ${CMAKE_BINARY_DIR}/pre.js
  DEPENDS ${CMAKE_SOURCE_DIR}/pre.js
)
ADD_CUSTOM_TARGET(CopyPreJs ALL
   DEPENDS ${CMAKE_BINARY_DIR}/pre.js
)



##########################################################
# headers to install
##########################################################
set(PYJS_HEADERS
    include/pyjs/convert.hpp
    include/pyjs/export_js_module.hpp
    include/pyjs/export_js_proxy.hpp
    include/pyjs/export_py_object.hpp
    include/pyjs/export_pyjs_module.hpp
    pre.js
)

set(PYCPPSOURCES "")
foreach(script ${PYCPPSCRIPTS})
    list(APPEND PYCPPSOURCES pycpp_includes/${script}.cpp)
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

add_library(pyjs STATIC
    src/export_js_module.cpp
    src/export_js_proxy.cpp
    src/export_py_object.cpp
    src/convert.cpp
    ${PYCPPSOURCES}
)

target_link_libraries(pyjs PRIVATE ${PYTHON_UTIL_LIBS} pybind11::embed)


    target_compile_options(pyjs
        PUBLIC --std=c++17
        PUBLIC -Wno-deprecated
        PUBLIC "SHELL: --bind"
        PUBLIC "SHELL: -fwasm-exceptions"
    )

    target_link_options(pyjs
        PUBLIC --bind
        PUBLIC -Wno-unused-command-line-argument
        PUBLIC "SHELL: --bind"
        PUBLIC "SHELL: -fwasm-exceptions"
    )



set_target_properties(pyjs PROPERTIES
    PUBLIC_HEADER "${PYJS_HEADERS}"
)

target_link_libraries(pyjs PRIVATE pybind11::pybind11)
target_compile_options(pyjs PRIVATE -fPIC)

target_include_directories(pyjs
                           PRIVATE
                           ${CMAKE_SOURCE_DIR}/include
                           ${CMAKE_CURRENT_BINARY_DIR}/pycpp_includes
)


SET(PYTHON_UTIL_LIBS
    ${CMAKE_INSTALL_PREFIX}/lib/libbz2.a
    ${CMAKE_INSTALL_PREFIX}/lib/libz.a
    ${CMAKE_INSTALL_PREFIX}/lib/libsqlite3.a
    ${CMAKE_INSTALL_PREFIX}/lib/libffi.a
)


# TODO MAKE LOOP

if(BUILD_RUNTIME_BROWSER)
    add_executable(pyjs_runtime_browser src/runtime.cpp )
    SET(ENVIRONMENT "web,worker")
    target_compile_definitions(pyjs_runtime_browser PUBLIC -DPYTEST_DRIVER_WEB)

    target_include_directories(pyjs_runtime_browser
                           PRIVATE
                           ${CMAKE_SOURCE_DIR}/include
                           ${CMAKE_CURRENT_BINARY_DIR}/pycpp_includes)

    set_target_properties(pyjs_runtime_browser
        PROPERTIES
            CXX_STANDARD 17
    )
    target_compile_definitions(pyjs_runtime_browser PUBLIC -DPYJS_WEB)
    target_compile_options(pyjs_runtime_browser PRIVATE -fPIC)
    target_link_libraries(pyjs_runtime_browser PRIVATE pyjs)
    target_link_libraries(pyjs_runtime_browser PRIVATE ${PYTHON_UTIL_LIBS} pybind11::embed)

    target_compile_options(pyjs_runtime_browser
        PUBLIC --std=c++17
        PUBLIC -Wno-deprecated
        PUBLIC "SHELL: --bind"
        PUBLIC "SHELL: -s ENVIRONMENT=${ENVIRONMENT}"
        PUBLIC "SHELL: -fwasm-exceptions"
        PUBLIC "SHELL: -s FORCE_FILESYSTEM"
        PUBLIC "SHELL: -s LZ4=1"
        PUBLIC "SHELL: -flto"
        # PUBLIC "SHELL: -s WASM_BIGINT"
    )

    target_link_options(pyjs_runtime_browser
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
        PUBLIC "SHELL: -s ENVIRONMENT=${ENVIRONMENT}"
        PUBLIC "SHELL: -s TOTAL_STACK=512mb"
        PUBLIC "SHELL: -s INITIAL_MEMORY=1024mb"
        PUBLIC "SHELL: -s FORCE_FILESYSTEM"
        PUBLIC "SHELL: -s LZ4=1"
        PUBLIC "SHELL: --post-js post.js"
        PUBLIC "SHELL: --pre-js pre.js"
        PUBLIC "SHELL: -flto"
        # PUBLIC "SHELL: -s WASM_BIGINT"
    )


    install(TARGETS pyjs_runtime_browser
            DESTINATION ${CMAKE_INSTALL_PREFIX}/lib_js/pyjs)
    install(FILES
            "$<TARGET_FILE_DIR:pyjs_runtime_browser>/pyjs_runtime_browser.wasm"
            DESTINATION ${CMAKE_INSTALL_PREFIX}/lib_js/pyjs)

endif()

if(BUILD_RUNTIME_NODE)



    add_executable(pyjs_runtime_node src/runtime.cpp )
    SET(ENVIRONMENT "node")
    target_compile_definitions(pyjs_runtime_node PUBLIC -DPYTEST_DRIVER_NODE)
    target_include_directories(pyjs_runtime_node
                           PRIVATE
                           ${CMAKE_SOURCE_DIR}/include
                           ${CMAKE_CURRENT_BINARY_DIR})




    set_target_properties(pyjs_runtime_node
        PROPERTIES
            CXX_STANDARD 17
    )
    target_compile_definitions(pyjs_runtime_node PUBLIC -DPYJS_WEB)
    target_compile_options(pyjs_runtime_node PRIVATE -fPIC)
    target_link_libraries(pyjs_runtime_node PRIVATE ${PYTHON_UTIL_LIBS} pybind11::embed pyjs)

    target_compile_options(pyjs_runtime_node
        PUBLIC --std=c++17
        PUBLIC -Wno-deprecated
        PUBLIC "SHELL: --bind"
        PUBLIC "SHELL: -s ENVIRONMENT=${ENVIRONMENT}"
        PUBLIC "SHELL: -fwasm-exceptions"
        PUBLIC "SHELL: -s FORCE_FILESYSTEM"
        PUBLIC "SHELL: -s LZ4=1"
        PUBLIC "SHELL: -flto"
        # PUBLIC "SHELL: -s WASM_BIGINT"
    )

    target_link_options(pyjs_runtime_node
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
        PUBLIC "SHELL: -s ENVIRONMENT=${ENVIRONMENT}"
        PUBLIC "SHELL: -s TOTAL_STACK=512mb"
        PUBLIC "SHELL: -s INITIAL_MEMORY=1024mb"
        PUBLIC "SHELL: -s FORCE_FILESYSTEM"
        PUBLIC "SHELL: -s LZ4=1"
        PUBLIC "SHELL: --post-js post.js"
        PUBLIC "SHELL: --pre-js pre.js"
        PUBLIC "SHELL: -flto"
        # PUBLIC "SHELL: -s WASM_BIGINT"
    )

    add_dependencies(pyjs_runtime_node CopyPreJs)



    configure_file(${CMAKE_CURRENT_SOURCE_DIR}/tests/test.js.in ${CMAKE_CURRENT_BINARY_DIR}/test.cjs @ONLY)
    if(WITH_NODE_TESTS)
        execute_process(
            COMMAND npm bin
            OUTPUT_VARIABLE NODE_BIN_PATH
        )
        message(STATUS "NODEBINPATH  " ${NODE_BIN_PATH})
        string(STRIP ${NODE_BIN_PATH} NODE_BIN_PATH)
        message(STATUS "P" ${NODE_BIN_PATH}/ava )
        add_custom_target(node_tests
            COMMAND "${NODE_BIN_PATH}/ava" "--timeout=20s" "--node-arguments=\"--no-experimental-fetch\"" "" test.cjs
            WORKING_DIRECTORY ${CMAKE_BINARY_DIR}
            DEPENDS pyjs_runtime_node)
    endif()


    install(TARGETS pyjs_runtime_node
            DESTINATION ${CMAKE_INSTALL_PREFIX}/lib_js/pyjs)
    install(FILES
            "$<TARGET_FILE_DIR:pyjs_runtime_node>/pyjs_runtime_node.wasm"
            DESTINATION ${CMAKE_INSTALL_PREFIX}/lib_js/pyjs)


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
