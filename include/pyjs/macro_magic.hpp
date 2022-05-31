#ifndef EMBIND11_MACRO_MAGIC_HPP
#define EMBIND11_MACRO_MAGIC_HPP

#include <pybind11/pybind11.h>
#include <pybind11/embed.h> 

#define PYTHON_INIT_DECL(module_name) \
void module_name##pseudo_init(py::module_ & m)

#define PYTHON_INIT(module_name) \
module_name##pseudo_init


#define BEGIN_PYTHON_INIT(module_name) \
namespace py = pybind11; \
void module_name##pseudo_init(py::module_ & m){ \
    py::object scope  = m.attr("__dict__");\
    py::exec(

#define END_PYTHON_INIT ,scope);}

#endif // EMBIND11_MACRO_MAGIC_HPP