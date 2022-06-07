#include <pybind11/pybind11.h>

#include <emscripten.h>
#include <emscripten/val.h>
#include <emscripten/bind.h>

#include <iostream>
#include <filesystem>

#include <pyjs/export_js_proxy.hpp>
#include <pyjs/macro_magic.hpp>

// python
#include <pyjs/core.py>
#include <pyjs/extend_js_val.py>
#include <pyjs/convert.py>
#include <pyjs/webloop.py>


namespace py = pybind11;
namespace em = emscripten;

namespace pyjs
{

void export_pyjs_module(py::module_ & pyjs_module)
{  
    export_js_proxy(pyjs_module);
    try{
        PYTHON_INIT(pyjs_core)(pyjs_module);
        PYTHON_INIT(pyjs_extend_js_val)(pyjs_module);
        PYTHON_INIT(pyjs_convert)(pyjs_module);
        PYTHON_INIT(pyjs_webloop)(pyjs_module);
    } 
    catch (py::error_already_set& e)
    {
        std::cout<<"error: "<<e.what()<<"\n";
        throw e;
    }
}

}