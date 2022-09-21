#pragma once

#include <pybind11/pybind11.h>


namespace py = pybind11;

namespace pyjs
{
    void export_js_proxy(py::module_& m);
}
