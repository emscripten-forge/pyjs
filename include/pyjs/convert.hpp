#pragma once
#include <pybind11/pybind11.h>
#include <pybind11/numpy.h>
#include <emscripten/val.h>
#include <string>

namespace py = pybind11;
namespace em = emscripten;

namespace pyjs
{

// std::string type_string(em::val em_val)
// {
//     return em_val.typeOf().as<std::string>();
// }
// bool is_array(em::val em_val)
// {
//     // return false;
//     return em::val::global("Array").call<em::val>("isArray", em_val).as<bool>();
// }


// bool is_undefined_or_none(em::val em_val)
// {
//     // return false;
//     return em::val::module_property("_is_undefined_or_null")(em_val).as<bool>();
// }


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

        // a byte-offset of 0 or 1 means continuous / dense data
        if(byte_offset <= 1)
        {

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
        else
        {

        }
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
}




}
