#pragma once
#include <pybind11/pybind11.h>
#include <pybind11/numpy.h>
#include <emscripten/val.h>
#include <string>

namespace py = pybind11;
namespace em = emscripten;







namespace pyjs
{

enum class JsType : char {
    JS_NULL = '0',
    JS_UNDEFINED = '1',
    JS_OBJECT = '2',
    JS_STR = '3',
    JS_INT = '4',
    JS_FLOAT = '5',
    JS_BOOL = '6',
    JS_FUNCTION = '7'
};




inline bool instanceof(em::val instance, const std::string & cls_name){
    return em::val::module_property("_instanceof")(instance, em::val::global(cls_name.c_str())).as<bool>();
};

template<class T>
py::object typed_array_to_numpy_array_impl(em::val js_array){


    em::val js_array_buffer = js_array["buffer"].as<em::val>();
    
    const unsigned byte_offset = js_array["byteOffset"].as<em::val>().as<unsigned>();
    const unsigned length = js_array["length"].as<unsigned> ();
    const unsigned bytes_per_element = js_array["BYTES_PER_ELEMENT"].as<unsigned>();
    const unsigned length_uint8 = length * bytes_per_element;

    // TODO skip for uint8!
    // convert js typed-array into an js-Uint8Array
    em::val js_uint8array = em::val::global("Uint8Array").new_(
        js_array_buffer, 
        byte_offset, 
        length * bytes_per_element
    );



    py::array_t<T> np_array( {py::ssize_t(length)});

    // copy values from js side to vectors mem
    // - create a javascript "UInt8(!) (not Int8) array"
    //   which is using the vector ptr as buffer
    em::val heap = em::val::module_property("HEAPU8");
    em::val memory = heap["buffer"];
    em::val memory_view = js_uint8array["constructor"].new_(memory, 
        reinterpret_cast<uintptr_t>(np_array.data()), 
        length_uint8);

    // - copy the js arrays content into the c++ arrays content
    memory_view.call<void>("set", js_uint8array);

    return np_array;
}


inline py::object  typed_array_to_numpy_array(em::val js_array){
    if(instanceof(js_array, "Int8Array"))
    {
        return typed_array_to_numpy_array_impl<int8_t>(js_array);
    }
    else if(instanceof(js_array, "Uint8Array"))
    {
        return typed_array_to_numpy_array_impl<uint8_t>(js_array);
    }
    else if(instanceof(js_array, "Uint8ClampedArray"))
    {
        return typed_array_to_numpy_array_impl<uint8_t>(js_array);
    }
    else if(instanceof(js_array, "Int16Array"))
    {
        return typed_array_to_numpy_array_impl<int16_t>(js_array);
    }
    else if(instanceof(js_array, "Uint16Array"))
    {
        return typed_array_to_numpy_array_impl<uint16_t>(js_array);
    }
    else if(instanceof(js_array, "Int32Array"))
    {
        return typed_array_to_numpy_array_impl<int32_t>(js_array);
    }
    else if(instanceof(js_array, "Uint32Array"))
    {
        return typed_array_to_numpy_array_impl<uint32_t>(js_array);
    }
    else if(instanceof(js_array, "Float32Array"))
    {
        return typed_array_to_numpy_array_impl<float>(js_array);
    }
    else if(instanceof(js_array, "Float64Array"))
    {
        return typed_array_to_numpy_array_impl<double>(js_array);
    }
    else if(instanceof(js_array, "BigInt64Array"))
    {
        return typed_array_to_numpy_array_impl<int64_t>(js_array);
    }
    else if(instanceof(js_array, "BigUint64Array"))
    {
        return typed_array_to_numpy_array_impl<uint64_t>(js_array);
    }
    else
    {
        throw pybind11::type_error("unknown array type");
    }
}


inline py::object implicit_to_py(
    em::val val,
    const std::string & type_string
)
{
    if(type_string.size() == 1)
    {
        const char s = type_string[0];
        switch(s)
        {
            case static_cast<char>(JsType::JS_NULL):
            {
                return  py::none();
            }
            case static_cast<char>(JsType::JS_UNDEFINED):
            {
                return  py::none();
            }
            // 2 is object
            case static_cast<char>(JsType::JS_STR):
            {
                return py::cast(val.as<std::string>());
            }
            case static_cast<char>(JsType::JS_INT):
            {
                const auto double_number = val.as<double>();
                const auto rounded_double_number = std::round(double_number);
                return py::cast(int(rounded_double_number));
            }
            case static_cast<char>(JsType::JS_FLOAT):
            {
                return py::cast(val.as<double>());
            }
            case static_cast<char>(JsType::JS_BOOL):
            {
                return py::cast(val.as<bool>());
            }
            default:
            {
                return py::cast(val);
            }
        }
    }
    else
    {
        return py::cast(val);
    }
}


}


