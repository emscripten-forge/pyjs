#pragma once
#include <pybind11/pybind11.h>

namespace py = pybind11;

namespace pyjs
{
    void export_pyjs_module(py::module_& pyjs_module);
}
