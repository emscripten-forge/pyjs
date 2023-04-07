#pragma once
#include <pybind11/pybind11.h>
#include <pybind11/numpy.h>
#include <emscripten/val.h>
#include <string>
#include <iostream>

namespace py = pybind11;
namespace em = emscripten;

namespace pyjs
{   


    struct TypedArrayBuffer{


        TypedArrayBuffer(
            em::val js_array, const std::string & format_descriptor
        );
        ~TypedArrayBuffer();

        unsigned m_size;
        unsigned m_bytes_per_element;
        uint8_t * m_data;
        std::string m_format_descriptor;
    };

    
    

    enum class JsType : char
    {
        JS_NULL = '0',
        JS_UNDEFINED = '1',
        JS_OBJECT = '2',
        JS_STR = '3',
        JS_INT = '4',
        JS_FLOAT = '5',
        JS_BOOL = '6',
        JS_FUNCTION = '7'
    };

    std::pair<em::val,bool> implicit_py_to_js(py::object & py_ret);

    bool instanceof (em::val instance, const std::string& cls_name);

  
    



    TypedArrayBuffer* typed_array_to_buffer(em::val js_array);
    py::object implicit_js_to_py(em::val val);
    py::object implicit_js_to_py(em::val val, const std::string& type_string);


    em::val py_1d_buffer_to_typed_array(py::buffer buffer, bool view);

}
