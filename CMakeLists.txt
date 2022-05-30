cmake_minimum_required(VERSION 3.9)
project(pyjs VERSION 0.1.0 DESCRIPTION "pyjs description")




set(PYJS_HEADERS
    include/pyjs/export_js_module.hpp
    include/pyjs/export_pyjs_module.hpp
)


set(CMAKE_CXX_STANDARD 14)
set(CMAKE_CXX_STANDARD_REQUIRED ON)


set(pybind11_REQUIRED_VERSION 2.6.1)

if (NOT TARGET pybind11::headers)
    find_package(pybind11 ${pybind11_REQUIRED_VERSION} REQUIRED)
endif ()




configure_file(pre.js  ${CMAKE_CURRENT_BINARY_DIR}/pre.js COPYONLY)


set(EM_FLAGS "${EM_FLAGS} -s WASM=1 --bind")

add_library(pyjs STATIC
    src/pyjs/export_js_module.cpp
    src/pyjs/export_pyjs_module.cpp
)



set_target_properties(pyjs PROPERTIES 
    LINK_FLAGS " ${EM_FLAGS} --pre-js pre.js"
    COMPILE_FLAGS "${EM_FLAGS}"
    # PUBLIC_HEADER "${PYJS_HEADERS}"
    PREFIX ""
    VERSION ${${PROJECT_NAME}_VERSION}
    SOVERSION ${${PROJECT_NAME}_VERSION}
    INSTALL_RPATH_USE_LINK_PATH TRUE

)
include_directories(${CMAKE_CURRENT_SOURCE_DIR}/src ${CMAKE_CURRENT_SOURCE_DIR}/include)


target_link_libraries(pyjs PUBLIC pybind11::pybind11)
target_compile_options(pyjs PRIVATE -fPIC)


target_include_directories(pyjs
                           PUBLIC
                           ${PYTHON_INCLUDE_DIRS} 
                           $<BUILD_INTERFACE:${BUILD_INCLUDES}>
                           $<INSTALL_INTERFACE:include>)



include(GNUInstallDirs)
include(CMakePackageConfigHelpers)

set(PYJS_CMAKECONFIG_INSTALL_DIR "${CMAKE_INSTALL_LIBDIR}/cmake/${PROJECT_NAME}" CACHE STRING "install path for pyjsConfig.cmake")


# Configure 'pyjsConfig.cmake' for an install tree
set(PYJS_CONFIG_CODE "")


# Configure 'xeus-pythonConfig.cmake' for a build tree
set(PYJS_CONFIG_CODE "####### Expanded from \@PYJS_CONFIG_CODE\@ #######\n")
set(PYJS_CONFIG_CODE "${PYJS_CONFIG_CODE}set(CMAKE_MODULE_PATH \"${CMAKE_CURRENT_SOURCE_DIR}/cmake;\${CMAKE_MODULE_PATH}\")\n")
set(PYJS_CONFIG_CODE "${PYJS_CONFIG_CODE}##################################################")
configure_package_config_file(${PROJECT_NAME}Config.cmake.in
                              "${CMAKE_CURRENT_BINARY_DIR}/${PROJECT_NAME}Config.cmake"
                              INSTALL_DESTINATION ${PROJECT_BINARY_DIR})

# Configure 'xeus-pythonConfig.cmake' for an install tree
set(PYJS_CONFIG_CODE "")


configure_package_config_file(${PROJECT_NAME}Config.cmake.in
                              "${CMAKE_CURRENT_BINARY_DIR}/CMakeFiles/${PROJECT_NAME}Config.cmake"
                              INSTALL_DESTINATION ${PYJS_CMAKECONFIG_INSTALL_DIR})



# set_target_properties(pyjs PROPERTIES
#         "INTERFACE_INCLUDE_DIRECTORIES" "include"
# )





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