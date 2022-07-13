#include <pybind11/pybind11.h>
#include <pybind11/numpy.h>
#include <pybind11/stl.h>

#include <emscripten.h>
#include <emscripten/val.h>
#include <emscripten/bind.h>

#include <iostream>
#include <filesystem>
#include <sstream>

#include <pyjs/convert.hpp>
#include <pyjs/mpool.hpp>

namespace py = pybind11;
namespace em = emscripten;

namespace pyjs
{






void export_mamba(py::module_ & m)
{   
    py::module_ m_internal = m.def_submodule("mamba", "mamba");


    py::class_<MPool>(m_internal, "MPool")
        .def(py::init<>())
        .def("solve",[](MPool & pool, std::vector<std::string> & match_specs){
            return  pool.solve(match_specs);
        })
        .def("load_repo", &MPool::load_repo)
    ;
   
}

}