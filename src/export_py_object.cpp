#include <emscripten/val.h>
#include <emscripten/bind.h>
#include <pyjs/convert.hpp>
#include <strings.h>
#include <iostream>
#include <pybind11/pybind11.h>

namespace py = pybind11;
namespace em = emscripten;

namespace pyjs
{
    template <class E>
    em::val wrap_py_err(E& e)
    {
        em::val ret = em::val::object();
        ret.set("has_err", em::val(true));
        ret.set("message", em::val(std::string(e.what())));
        ret.set("error", em::val(std::string(e.what())));
        return ret;
    }

    em::val raw_apply(py::object& self,
                      em::val args,
                      em::val args_types,
                      std::size_t n_args,
                      em::val kwargs_keys,
                      em::val kwargs_values,
                      em::val kwargs_values_types,
                      std::size_t n_kwargs)
    {
        py::gil_scoped_acquire acquire;
        py::list py_args;
        py::dict py_kwargs;
        for (std::size_t i = 0; i < n_args; ++i)
        {
            py::object py_arg = implicit_to_py(args[i], args_types[i].as<std::string>());
            py_args.append(py_arg);
        }

        for (std::size_t i = 0; i < n_kwargs; ++i)
        {
            py::object py_kwarg_val
                = implicit_to_py(kwargs_values[i], kwargs_values_types[i].as<std::string>());
            const std::string key = kwargs_keys[i].as<std::string>();
            py_kwargs[py::cast(key)] = py_kwarg_val;
        }


        try
        {
            em::val ret = em::val::object();
            py::object py_ret = self(*py_args, **py_kwargs);
            ret.set("has_err", em::val(false));
            ret.set("ret", implicit_conversion(py_ret));
            return ret;
        }
        catch (py::error_already_set& e)
        {
            return wrap_py_err(e);
        }
        catch (std::exception& e)
        {
            return wrap_py_err(e);
        }
    }


    em::val raw_call(py::object& pyobject, em::val args, em::val arg_types, std::size_t n_args)
    {
        py::gil_scoped_acquire acquire;


        py::list py_args;
        for (std::size_t i = 0; i < n_args; ++i)
        {
            py::object py_arg = implicit_to_py(args[i], arg_types[i].as<std::string>());
            py_args.append(py_arg);
        }

        try
        {
            em::val ret = em::val::object();
            py::object py_ret = pyobject(*py_args);
            ret.set("has_err", em::val(false));
            ret.set("ret", implicit_conversion(py_ret));
            return ret;
        }
        catch (py::error_already_set& e)
        {
            return wrap_py_err(e);
        }
        catch (std::exception& e)
        {
            return wrap_py_err(e);
        }
    }

    void export_py_object()
    {
        em::class_<py::object>("pyobject")


            .function("_raw_apply", &raw_apply)

            .function("_raw_call", &raw_call)

            .function(
                "_raw_getitem",
                em::select_overload<em::val(py::object&, em::val, em::val, std::size_t)>(
                    [](py::object& pyobject, em::val args, em::val arg_types, std::size_t n_keys)
                        -> em::val
                    {
                        py::gil_scoped_acquire acquire;


                        // implicit to py

                        py::list py_args;
                        for (std::size_t i = 0; i < n_keys; ++i)
                        {
                            py::object py_arg
                                = implicit_to_py(args[i], arg_types[i].as<std::string>());
                            py_args.append(py_arg);
                        }

                        try
                        {
                            em::val ret = em::val::object();
                            ret.set("has_err", em::val(false));
                            if (n_keys == 0)
                            {
                                py::object py_ret = pyobject.attr("__getitem__")();
                                ret.set("ret", implicit_conversion(py_ret));
                            }
                            if (n_keys == 1)
                            {
                                py::object py_ret = pyobject.attr("__getitem__")(py_args[0]);
                                ret.set("ret", implicit_conversion(py_ret));
                            }
                            else
                            {
                                py::tuple tuple_args(py_args);
                                py::object py_ret = pyobject.attr("__getitem__")(tuple_args);
                                ret.set("ret", implicit_conversion(py_ret));
                            }
                            return ret;
                        }
                        catch (py::error_already_set& e)
                        {
                            return wrap_py_err(e);
                        }
                        catch (std::exception& e)
                        {
                            return wrap_py_err(e);
                        }
                    }))


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
                      em::select_overload<em::val(py::object&, const std::string&)>(
                          [](py::object& pyobject, const std::string& attr_name) -> em::val
                          {
                              em::val ret = em::val::object();
                              try
                              {
                                  py::object py_ret = pyobject.attr(attr_name.c_str());
                                  ret.set("has_err", em::val(false));
                                  ret.set("ret", implicit_conversion(py_ret));
                                  return ret;
                              }
                              catch (py::error_already_set& e)
                              {
                                  ret.set("has_err", em::val(true));
                                  ret.set("message", em::val(std::string(e.what())));
                                  ret.set("error", em::val(std::string(e.what())));
                                  return ret;
                              }
                          }))


            ;
    }

}
