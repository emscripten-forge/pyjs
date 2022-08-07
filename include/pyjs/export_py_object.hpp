#include <emscripten/val.h>
#include <emscripten/bind.h>
#include <pyjs/convert.hpp>
#include <strings.h>

namespace py = pybind11;
namespace em = emscripten;

namespace pyjs
{
    void export_py_object()
    {
        em::class_<py::object>("pyobject")
            // 0-ary
            .function("__call__",
                      em::select_overload<em::val(py::object&)>(
                          [](py::object& pyobject) -> em::val
                          {
                              try
                              {
                                  py::gil_scoped_acquire acquire;
                                  py::object ret = pyobject();
                                  return em::val(std::move(ret));
                              }
                              catch (py::error_already_set& e)
                              {
                                  std::cout << "error: " << e.what() << "\n";
                                  return em::val::null();
                              }
                          }))
            // 1-ary
            .function("__call__",
                      em::select_overload<em::val(py::object&, em::val)>(
                          [](py::object& pyobject, em::val arg1) -> em::val
                          {
                              try
                              {
                                  py::gil_scoped_acquire acquire;
                                  py::object ret = pyobject(arg1);
                                  return em::val(std::move(ret));
                              }
                              catch (py::error_already_set& e)
                              {
                                  std::cout << "error: " << e.what() << "\n";
                                  return em::val::null();
                              }
                          }))

            .function("__usafe_void_void__",
                      em::select_overload<void(py::object&)>(
                          [](py::object& pyobject)
                          {
                              {
                                  py::gil_scoped_acquire acquire;
                                  pyobject();
                              }
                          }))

            .function("__usafe_void_val__",
                      em::select_overload<void(py::object&, em::val)>(
                          [](py::object& pyobject, em::val val)
                          {
                              {
                                  py::gil_scoped_acquire acquire;
                                  pyobject(val);
                              }
                          }))

            .function("__usafe_void_val_val__",
                      em::select_overload<void(py::object&, em::val, em::val)>(
                          [](py::object& pyobject, em::val val1, em::val val2)
                          {
                              {
                                  py::gil_scoped_acquire acquire;
                                  pyobject(val1, val2);
                              }
                          }))

            .function("_raw_getattr",
                      em::select_overload<em::val(py::object&, const std::string & )>(
                          [](py::object& pyobject,const std::string & attr_name) -> em::val
                          {


                            em::val ret = em::val::object();
                            try
                            {
                                py::object py_ret = pyobject.attr(attr_name.c_str());
                                ret.set("has_err",em::val(false));
                                ret.set("ret",implicit_conversion(py_ret));
                                return ret;
                            }
                            catch (py::error_already_set& e)
                            {
                               ret.set("has_err",em::val(true));
                               ret.set("message",em::val(std::string(e.what())));
                               ret.set("error",em::val(std::string(e.what())));
                               return ret;
                            }
                          }))



            ;
    }

}
