#include <pybind11/pybind11.h>
#include <pybind11/numpy.h>

#include <emscripten.h>
#include <emscripten/val.h>
#include <emscripten/bind.h>

#include <iostream>
#include <filesystem>

#include <pyjs/convert.hpp>

namespace py = pybind11;
namespace em = emscripten;

namespace pyjs
{

void export_js_proxy(py::module_ & m)
{   


    py::module_ m_internal = m.def_submodule("internal", "A submodule of 'embind11'");



    m_internal.def("global_property", [](const std::string & arg){
        return em::val::global(arg.c_str());
    });

    m_internal.def( "module_property", [](const std::string & arg){
        return em::val::module_property(arg.c_str());
    });


    m.def("js_array", [](){return em::val::array();});
    m.def("js_object", [](){return em::val::object();});
    m.def("js_undefined", [](){return em::val::undefined();});
    m.def("js_null", [](){return em::val::null();});
    m.def("js_py_object",[](py::object py_object){
        return em::val(std::move(py_object));
    }, py::return_value_policy::copy);


    m.def("instanceof",[](em::val * instance, em::val * cls){
        return em::val::module_property("_instanceof")(*instance, *cls).as<bool>();
    });


    m_internal.def("val_call",[](em::val * v, const std::string & key, em::val & arg1){
        return v->call<em::val>(key.c_str(), arg1);
    });

    m_internal.def("val_call",[](em::val * v, const std::string & key, em::val & arg1,  em::val & arg2){
        return v->call<em::val>(key.c_str(), arg1, arg2);
    });

    m_internal.def("val_function_call",[](em::val * v){
        return v->operator()();
    });
    m_internal.def("val_function_call",[](em::val * v, em::val  arg1){
        return v->operator()(arg1);
    });
    m_internal.def("val_function_call",[](em::val * v, em::val  arg1,  em::val  arg2){
        return v->operator()(arg1, arg2);
    });
    m_internal.def("val_function_call",[](em::val * v, em::val  arg1,  em::val  arg2,  em::val  arg3){
        return v->operator()(arg1, arg2, arg3);
    });
    m_internal.def("val_function_call",[](em::val * v, em::val  arg1,  em::val  arg2,  em::val  arg3,  em::val  arg4){
        return v->operator()(arg1, arg2, arg3, arg4);
    });

    m_internal.def("val_bind", [](em::val * v, em::val  arg1){
            return v->call<em::val>("bind", arg1);
    });


    m_internal.def("val_new",[](em::val  v){
            return  v.new_();
        });
    m_internal.def("val_new",[](em::val  v, em::val arg1){
            return  v.new_(arg1);
        });



    m_internal.def("as_int",[](em::val * v) -> int {
        return  v->as<int>();
    });
    m_internal.def("as_double",[](em::val * v) -> double {
        return  v->as<double>();
    });
    m_internal.def("as_float",[](em::val * v) -> float {
        return  v->as<float>();
    });
    m_internal.def("as_boolean",[](em::val * v) -> bool {
        return  v->as<bool>();
    });
    m_internal.def("as_string",[](em::val * v) -> std::string {
        return  v->as<std::string>();
    });

    m_internal.def("as_numpy_array",[](em::val * v) -> py::object {
        return  typed_array_to_numpy_array(*v);
    });

    m_internal.def("as_py_object",[](em::val * v) -> py::object {
        return  v->as<py::object>();
    });

    // type queries


    // m_internal.def("cout",[](const std::string & val1) {
    //     std::cout<<val1;
    // });

    m_internal.def("console_log",[](em::val  val1) {
        em::val::global("console").call<void>("log",val1);
    });
    m_internal.def("console_log",[](em::val val1, em::val val2) {
        em::val::global("console").call<void>("log",val1, val2);
    });
    m_internal.def("console_log",[](em::val val1, em::val val2, em::val val3) {
        em::val::global("console").call<void>("log",val1, val2, val3);
    });
    m_internal.def("console_log",[](em::val val1, em::val val2, em::val val3, em::val val4) {
        em::val::global("console").call<void>("log",val1, val2, val3,val4);
    });


    m_internal.def("get_type_string",[](em::val * val) -> std::string {
        return em::val::module_property("_get_type_string")(*val).as<std::string>();
    });



    m_internal.def("is_null",[](em::val * val) -> bool {
        return em::val::module_property("_is_null")(*val).as<bool>();
    });

    m_internal.def("is_undefined",[](em::val * val) -> bool {
        return em::val::module_property("_is_undefined")(*val).as<bool>();
    });

    m_internal.def("is_undefined_or_null",[](em::val * val) -> bool {
        return em::val::module_property("_is_undefined_or_null")(*val).as<bool>();
    });

    m_internal.def("is_array",[](em::val * val) -> bool {
        return em::val::module_property("_is_array")(*val).as<bool>();
    });

    m_internal.def("is_object",[](em::val * val) -> bool {
        return em::val::module_property("_is_object")(*val).as<bool>();
    });

    m_internal.def("is_number",[](em::val * val) -> bool {
        return em::val::module_property("_is_number")(*val).as<bool>();
    });

    m_internal.def("is_integer",[](em::val * val) -> bool {
        return em::val::module_property("_is_integer")(*val).as<bool>();
    });

    m_internal.def("is_boolean",[](em::val * val) -> bool {
        return em::val::module_property("_is_boolean")(*val).as<bool>();
    });
    m_internal.def("is_string",[](em::val * val) -> bool {
        return em::val::module_property("_is_string")(*val).as<bool>();
    });

    m_internal.def("is_typed_array",[](em::val * val) -> bool {
        return em::val::module_property("_is_typed_array")(*val).as<bool>();
    });


    m_internal.def("getattr_try_catch",[](em::val * val, const std::string & attr_name){
        return em::val::module_property("_getattr_try_catch")(*val, attr_name);
    });

    m_internal.def("getattr_try_catch",[](em::val * val, int index){
        return em::val::module_property("_getattr_try_catch")(*val, index);
    });


    m_internal.def("setattr_try_catch",[](em::val * val, const std::string & attr_name, em::val * attr_val){
        return em::val::module_property("_setattr_try_catch")(*val, attr_name,*attr_val);
    });

    m_internal.def("setattr_try_catch",[](em::val * val, int index, em::val * attr_val){
        return em::val::module_property("_setattr_try_catch")(*val, index,*attr_val);
    });

    m_internal.def("is_error",[](em::val * val){
        const std::string ts = val->typeOf().as<std::string>();
        if(ts == "object"){
            if(val->hasOwnProperty("__pyjs__error__"))
            {
                return true;
            }
        }
        return false;
    });

    m_internal.def("get_error",[](em::val * val){
        return val->operator[]("__pyjs__error__");
    });
    



    m_internal.def("__getitem__",[](em::val * v, const std::string & key){
        return  v->operator[](key);
    });

    m_internal.def("__getitem__",[](em::val * v, int index){
        return  v->operator[](index);
    });


    m_internal.def("object_keys",[](em::val * v){
        return  em::val::global("Object").call<em::val>("keys", *v);
    });
    m_internal.def("object_values",[](em::val * v){
        return  em::val::global("Object").call<em::val>("values", *v);
    });
    

    m_internal.def("length",[](em::val * v)->int{
        return  v->operator[]("length").as<int>();
    });

    m_internal.def("type_str",[](em::val * v){
        return v->typeOf().as<std::string>();
    });
    


    py::class_<em::val>(m, "JsValue",  py::dynamic_attr())

        .def(py::init([](std::string arg) {
            return std::unique_ptr<em::val>(new em::val(arg.c_str()));
        }))
        .def(py::init([](int arg) {
            return std::unique_ptr<em::val>(new em::val(arg));
        }))
        .def(py::init([](float arg) {
            return std::unique_ptr<em::val>(new em::val(arg));
        }))
        .def(py::init([](double arg) {
            return std::unique_ptr<em::val>(new em::val(arg));
        }))
        .def(py::init([](bool arg) {
            return std::unique_ptr<em::val>(new em::val(arg));
        }))
    
        // .def("new",[](em::val  v){
        //     return  v.new_();
        // })
        // .def("new",[](em::val  v, em::val arg1){
        //     return  v.new_(arg1);
        // })
        // .def("__bool__",[](em::val * v){
        //     return  v->as<bool>();
        // })
        .def_static("has_own_property",[](em::val * v, const std::string & key){
            return  v->hasOwnProperty(key.c_str( ));
        })



        .def("set_pyobject",[](em::val * v, const std::string & key, py::object pyobject){
            return  v->set(key, pyobject);
        })
        .def("__setitem__",[](em::val * v, const std::string & key, em::val & val){
            return  v->set(key, val);
        })



        .def_static("type_string", [](em::val * v){
            return v->typeOf().as<std::string>();
        })

        // .def("keys", [](em::val * v){
        //     auto keys =  em::val::global("Object").call<em::val>("keys", *v);
        //     int length = keys["length"].as<int>();
        //     // for (int i = 0; i < length; ++i) {
        //     //     printf("%s\n", keys[i].as<std::string>().c_str());
        //     // }
        //     return keys;
        // })
        .def("try_length",[](em::val * v){
            if(v->hasOwnProperty("length"))
            {
                return v->operator[]("length").as<int>();
            }
            else
            {
                return -1;
            }
        })
        .def("type_of", [](em::val * v){
            return v->typeOf();
        })
        .def("as_string", [](em::val * v){
            return v->as<std::string>();
        })
        

    ;

    py::implicitly_convertible<std::string, em::val>();
    py::implicitly_convertible<float, em::val>();
    py::implicitly_convertible<double, em::val>();
    py::implicitly_convertible<int, em::val>();
    py::implicitly_convertible<bool, em::val>();
}

}