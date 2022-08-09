# pragma once

#include <emscripten/bind.h>
#include <pybind11/pybind11.h>


namespace pyjs
{
    namespace em = emscripten;




    int n_unfinished();

    std::string run_pickled(const std::string& in);

    em::val eval(py::scoped_interpreter  & ,const  std::string & code, const py::object & scope);


    em::val exec(py::scoped_interpreter  & ,const  std::string & code, const py::object & scope);

    em::val eval_file(py::scoped_interpreter  & ,const  std::string & filename, const py::object & scope);


    void export_js_module();
}
