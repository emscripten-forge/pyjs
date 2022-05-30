#include <pybind11/pybind11.h>


#include <emscripten.h>
#include <emscripten/val.h>
#include <emscripten/bind.h>

#include <iostream>
#include <filesystem>

#include <pyjs/export_js_proxy.hpp>
#include <pyjs/pure_python_init.hppy>
#include <pyjs/macro_magic.hpp>



namespace py = pybind11;
namespace em = emscripten;

namespace pyjs
{

void export_pyjs_module(py::module_ & pyjs_module)
{  
    export_js_proxy(pyjs_module);
    PYTHON_INIT(pyjs)(pyjs_module);
}

}