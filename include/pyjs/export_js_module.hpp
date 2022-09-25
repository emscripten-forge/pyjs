# pragma once

#include <emscripten/bind.h>
#include <pybind11/pybind11.h>

namespace pyjs
{


    namespace em = emscripten;

    int n_unfinished();

    std::string run_pickled(const std::string& in);

    em::val eval(py::scoped_interpreter  & ,const  std::string & code, py::object & globals, py::object & locals);

    em::val exec(py::scoped_interpreter  & ,const  std::string & code, py::object & globals, py::object & locals);

    em::val eval_file(py::scoped_interpreter  & ,const  std::string & filename, py::object & globals, py::object & locals);


    void export_js_module();
}
