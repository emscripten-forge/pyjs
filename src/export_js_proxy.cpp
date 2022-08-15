#include <pybind11/pybind11.h>
#include <pybind11/numpy.h>

#include <emscripten.h>
#include <emscripten/val.h>
#include <emscripten/bind.h>

#include <iostream>
#include <filesystem>
#include <sstream>

#include <pyjs/convert.hpp>

namespace py = pybind11;
namespace em = emscripten;

namespace pyjs
{
    inline py::object wrap_result(em::val wrapped_return_value, const bool has_err)
    {
        if (has_err)
        {
            py::module pyjs = py::module::import("pyjs");
            pyjs.attr("error_to_py_and_raise")(wrapped_return_value["err"]);
        }
        const bool has_ret = wrapped_return_value["has_ret"].as<bool>();
        const auto type_string = wrapped_return_value["type_string"].as<std::string>();
        if (has_ret)
        {
            py::tuple ret_tuple = py::make_tuple(
                implicit_to_py(wrapped_return_value["ret"], type_string), type_string);
            return ret_tuple;
        }
        else
        {
            py::tuple ret_tuple = py::make_tuple(py::none(), type_string);
            return ret_tuple;
        }
    }

    inline py::object wrap_result(em::val wrapped_return_value)
    {
        const bool has_err = wrapped_return_value["has_err"].as<bool>();
        return wrap_result(wrapped_return_value, has_err);
    }


    inline void wrap_void(em::val wrapped_return_value)
    {
        const bool has_err = wrapped_return_value["has_err"].as<bool>();

        if (has_err)
        {
            py::module pyjs = py::module::import("pyjs");
            pyjs.attr("error_to_py_and_raise")(wrapped_return_value["err"]);
        }
    }


    inline py::object getattr(em::val* self, em::val* key)
    {
        em::val wrapped_return_value = em::val::module_property("_getattr_try_catch")(*self, *key);

        const bool has_ret = wrapped_return_value["has_ret"].as<bool>();
        const bool has_err = wrapped_return_value["has_err"].as<bool>();

        if (has_err)
        {
            py::module pyjs = py::module::import("pyjs");
            pyjs.attr("error_to_py_and_raise")(wrapped_return_value["err"]);
        }

        const auto type_string = wrapped_return_value["type_string"].as<std::string>();
        if (type_string == "0")
        {
            return py::none();
        }
        else if (type_string == "1")
        {
            std::stringstream ss;
            ss << "has no attribute/key ";
            throw pybind11::attribute_error(ss.str());
        }
        return implicit_to_py(wrapped_return_value["ret"], type_string);
    }

    void export_js_proxy(py::module_& m)
    {
        py::module_ m_internal = m.def_submodule("internal", "implementation details of of pyjs");

        m_internal.def("global_property",
                       [](const std::string& arg)
                       {
                           em::val v = em::val::global(arg.c_str());
                           const std::string type_string
                               = em::val::module_property("_get_type_string")(v).as<std::string>();
                           return implicit_to_py(v, type_string);
                       });

        m_internal.def("module_property",
                       [](const std::string& arg)
                       {
                           em::val v = em::val::module_property(arg.c_str());
                           return v;
                       });


        m_internal.def("apply_try_catch",
                       [](em::val* js_function, em::val* args) -> py::object {
                           return wrap_result(
                               em::val::module_property("_apply_try_catch")(*js_function, *args));
                       });

        m_internal.def("japply_try_catch",
                       [](em::val* js_function, em::val* jargs) -> py::object {
                           return wrap_result(
                               em::val::module_property("_japply_try_catch")(*js_function, *jargs));
                       });

        m_internal.def("gapply_try_catch",
                       [](em::val* js_function, em::val* jargs, bool jin, bool jout) -> py::object
                       {
                           em::val wrapped_return_value = em::val::module_property(
                               "_gapply_try_catch")(*js_function, *jargs, jin, jout);
                           const bool has_err = wrapped_return_value["has_err"].as<bool>();
                           if (has_err)
                           {
                               py::module pyjs = py::module::import("pyjs");
                               pyjs.attr("error_to_py_and_raise")(wrapped_return_value["err"]);
                           }
                           if (jout)
                           {
                               em::val out = wrapped_return_value["ret"];
                               return py::cast(out.as<std::string>());
                           }
                           else
                           {
                               return wrap_result(wrapped_return_value, has_err);
                           }
                       });

        m_internal.def(
            "getattr_try_catch",
            [](em::val* obj, em::val* key) -> py::object
            { return wrap_result(em::val::module_property("_getattr_try_catch")(*obj, *key)); });


        m_internal.def(
            "setattr_try_catch",
            [](em::val* obj, em::val* key, em::val* value)
            { wrap_void(em::val::module_property("_setattr_try_catch")(*obj, *key, *value)); });



        m.def("js_int", [](const int v) { return em::val(v); });

        m.def("js_array", []() { return em::val::array(); });
        m.def("js_object", []() { return em::val::object(); });
        m.def("js_undefined", []() { return em::val::undefined(); });
        m.def("js_null", []() { return em::val::null(); });
        m.def("js_py_object",
              [](const py::object& py_object)
              {
                  py::object cp(py_object);
                  py_object.inc_ref();
                  return em::val(std::move(cp));
              });


        m.def("instanceof",
              [](em::val* instance, em::val* cls)
              { return em::val::module_property("_instanceof")(*instance, *cls).as<bool>(); });


        m_internal.def("val_call",
                       [](em::val* v, const std::string& key, em::val& arg1)
                       { return v->call<em::val>(key.c_str(), arg1); });

        m_internal.def("val_call",
                       [](em::val* v, const std::string& key, em::val& arg1, em::val& arg2)
                       { return v->call<em::val>(key.c_str(), arg1, arg2); });

        m_internal.def("val_function_call", [](em::val* v) { return v->operator()(); });
        m_internal.def("val_function_call",
                       [](em::val* v, em::val arg1) { return v->operator()(arg1); });
        m_internal.def("val_function_call",
                       [](em::val* v, em::val arg1, em::val arg2)
                       { return v->operator()(arg1, arg2); });
        m_internal.def("val_function_call",
                       [](em::val* v, em::val arg1, em::val arg2, em::val arg3)
                       { return v->operator()(arg1, arg2, arg3); });
        m_internal.def("val_function_call",
                       [](em::val* v, em::val arg1, em::val arg2, em::val arg3, em::val arg4)
                       { return v->operator()(arg1, arg2, arg3, arg4); });

        m_internal.def("val_bind",
                       [](em::val* v, em::val arg1) { return v->call<em::val>("bind", arg1); });

        // m_internal.def("val_new",[](em::val  v){
        //     return  v.new_();
        // });
        // m_internal.def("val_new",[](em::val  v, em::val arg1){
        //     return  v.new_(arg1);
        // });

        m_internal.def("as_int", [](em::val* v) -> int { return v->as<int>(); });
        m_internal.def("as_double", [](em::val* v) -> double { return v->as<double>(); });
        m_internal.def("as_float", [](em::val* v) -> float { return v->as<float>(); });
        m_internal.def("as_boolean", [](em::val* v) -> bool { return v->as<bool>(); });
        m_internal.def("as_string", [](em::val* v) -> std::string { return v->as<std::string>(); });

        m_internal.def("as_numpy_array",
                       [](em::val* v) -> py::object { return typed_array_to_numpy_array(*v); });

        m_internal.def("as_py_object",
                       [](em::val* v) -> py::object { return v->as<py::object>(); });

        // type queries
        m_internal.def("console_log",
                       [](em::val val1) { em::val::global("console").call<void>("log", val1); });
        m_internal.def("console_log",
                       [](em::val val1, em::val val2)
                       { em::val::global("console").call<void>("log", val1, val2); });
        m_internal.def("console_log",
                       [](em::val val1, em::val val2, em::val val3)
                       { em::val::global("console").call<void>("log", val1, val2, val3); });
        m_internal.def("console_log",
                       [](em::val val1, em::val val2, em::val val3, em::val val4)
                       { em::val::global("console").call<void>("log", val1, val2, val3, val4); });


        m_internal.def(
            "get_type_string",
            [](em::val* val) -> std::string
            { return em::val::module_property("_get_type_string")(*val).as<std::string>(); });


        m_internal.def("is_null",
                       [](em::val* val) -> bool
                       { return em::val::module_property("_is_null")(*val).as<bool>(); });

        m_internal.def("is_undefined",
                       [](em::val* val) -> bool
                       { return em::val::module_property("_is_undefined")(*val).as<bool>(); });

        m_internal.def(
            "is_undefined_or_null",
            [](em::val* val) -> bool
            { return em::val::module_property("_is_undefined_or_null")(*val).as<bool>(); });


        m_internal.def("is_error",
                       [](em::val* val)
                       {
                           const std::string ts = val->typeOf().as<std::string>();
                           if (ts == "object")
                           {
                               if (val->hasOwnProperty("__pyjs__error__"))
                               {
                                   return true;
                               }
                           }
                           return false;
                       });

        m_internal.def("get_error",
                       [](em::val* val) { return val->operator[]("__pyjs__error__"); });


        m_internal.def("__getitem__",
                       [](em::val* v, const std::string& key) { return v->operator[](key); });

        m_internal.def("__getitem__", [](em::val* v, int index) { return v->operator[](index); });


        m_internal.def("object_keys",
                       [](em::val* v)
                       { return em::val::global("Object").call<em::val>("keys", *v); });
        m_internal.def("object_values",
                       [](em::val* v)
                       { return em::val::global("Object").call<em::val>("values", *v); });


        m_internal.def("length",
                       [](em::val* v) -> int { return v->operator[]("length").as<int>(); });

        m_internal.def("type_str", [](em::val* v) { return v->typeOf().as<std::string>(); });


        m_internal.def("to_string",
                       [](em::val* v) -> std::string { return v->call<std::string>("toString"); });
        // this class is heavy extended on the python side
        // py::class_<em::val>(m, "JsValue",  py::dynamic_attr())
        py::class_<em::val>(m, "JsValue")  //,  py::dynamic_attr())

            .def(py::init([](std::string arg)
                          { return std::unique_ptr<em::val>(new em::val(arg.c_str())); }))
            .def(py::init([](bool arg) { return std::unique_ptr<em::val>(new em::val(arg)); }))

            .def(py::init([](int arg) { return std::unique_ptr<em::val>(new em::val(arg)); }))
            .def(py::init([](float arg) { return std::unique_ptr<em::val>(new em::val(arg)); }))
            .def(py::init([](double arg) { return std::unique_ptr<em::val>(new em::val(arg)); }))

            .def(py::init([](py::object obj)
                          { return std::unique_ptr<em::val>(new em::val(std::move(obj))); }))

            .def("__getattr__", &getattr)
            .def("__getitem__", &getattr)
            .def("__setattr__",
                 [](em::val* obj, em::val* key, em::val* value)
                 { wrap_void(em::val::module_property("_setattr_try_catch")(*obj, *key, *value)); })
            .def("__setitem__",
                 [](em::val* obj, em::val* key, em::val* value) {
                     wrap_void(em::val::module_property("_setattr_try_catch")(*obj, *key, *value));
                 });

        py::implicitly_convertible<std::string, em::val>();
        py::implicitly_convertible<float, em::val>();
        py::implicitly_convertible<double, em::val>();
        py::implicitly_convertible<int, em::val>();
        py::implicitly_convertible<bool, em::val>();



        m_internal.def("py_1d_buffer_to_typed_array", &py_1d_buffer_to_typed_array);

    }

}
