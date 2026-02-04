#include <pybind11/pybind11.h>
#include <pybind11/numpy.h>

#include <emscripten/val.h>
#include <string>
#include <sstream>
#include <pyjs/convert.hpp>

namespace py = pybind11;
namespace em = emscripten;


namespace pyjs
{
    std::pair<em::val,bool> implicit_py_to_js(py::object& py_ret)
    {
        // py::module_ pyjs = py::module_::import("pyjs_utils");
        // const std::string info = pyjs.attr("implicit_convert_info")(py_ret).cast<std::string>(); 


        const std::string info = py_ret.get_type().attr("__name__").str();
        
        if (info == "int")
        {
            auto emval = em::val(py_ret.cast<int>());
            return std::make_pair(std::move(emval),false);
        }
        else if (info == "str")
        {
            return std::make_pair(em::val(py_ret.cast<std::wstring>()),false);
        }
        else if (info == "bool")
        {
            return std::make_pair(em::val(py_ret.cast<bool>()),false);
        }
        else if (info == "double" || info == "float")
        {
            return std::make_pair(em::val(py_ret.cast<double>()),false);
        }
        else if (info == "NoneType")
        {
            return std::make_pair(em::val::undefined(),false);
        }
        else if (info == "JsValue")
        {
            return std::make_pair(py_ret.cast<em::val>(),false);
        }
        else if(info == "Task" || info == "coroutine")
        {
            return std::make_pair(em::val::module_property("_future_to_promise")(em::val(py_ret)),false);
        }
        else if(py::hasattr(py_ret,"implicit_to_js")){
            auto implicit_to_js = py_ret.attr("implicit_to_js");
            py::object py_js_ret = implicit_to_js();
            return std::make_pair(py_js_ret.cast<em::val>(),false);
        }
        else
        {
            return std::make_pair(em::val::module_property("make_proxy")(em::val(py_ret)),true);
        }
    }


    py::object implicit_js_to_py(em::val val, const std::string& type_string)
    {
        if (type_string.size() == 1)
        {
            const char s = type_string[0];
            switch (s)
            {
                case static_cast<char>(JsType::JS_NULL):
                {
                    return py::none();
                }
                case static_cast<char>(JsType::JS_UNDEFINED):
                {
                    return py::none();
                }
                // 2 is object
                case static_cast<char>(JsType::JS_STR):
                {
                    return py::cast(val.as<std::wstring>());
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
        else if (type_string == "pyobject")
        {
            return val.as<py::object>();
        }
        else
        {
            return py::cast(val);
        }
    }

    py::object implicit_js_to_py(em::val val)
    {
        const auto type_string = em::val::module_property("_get_type_string")(val).as<std::string>();
        return implicit_js_to_py(val, type_string);
    }


    bool instanceof (em::val instance, const std::string& cls_name)
    {
        return em::val::module_property("_instanceof")(instance, em::val::global(cls_name.c_str()))
            .as<bool>();
    };


    TypedArrayBuffer::TypedArrayBuffer(
       em::val js_array, const std::string & format_descriptor
    )
    : m_size(js_array["length"].as<unsigned>()),
      m_bytes_per_element(js_array["BYTES_PER_ELEMENT"].as<unsigned>()),
      m_format_descriptor(format_descriptor),
      m_data(new uint8_t[m_size * m_bytes_per_element])
    {   
        // Get the ArrayBuffer backing the JS TypedArray
        em::val js_array_buffer = js_array["buffer"];
    
        // Offset within the ArrayBuffer
        const unsigned byte_offset = js_array["byteOffset"].as<unsigned>();
    
        // Create a Uint8Array view of the source JS array
        em::val js_uint8array = em::val::global("Uint8Array")
                                    .new_(js_array_buffer, byte_offset, m_size * m_bytes_per_element);
    
        // Create a typed_memory_view for the C++ buffer
        em::val cpp_view = em::val(emscripten::typed_memory_view(
            m_size * m_bytes_per_element,
            m_data
        ));
    
        // Copy data from JS array into C++ buffer
        cpp_view.call<void>("set", js_uint8array);
    }

    TypedArrayBuffer::~TypedArrayBuffer(){
        delete[] m_data;
    }

    TypedArrayBuffer* typed_array_to_buffer(em::val js_array)
    {
        if (instanceof (js_array, "Int8Array"))
        {
            return new TypedArrayBuffer(js_array, py::format_descriptor<int8_t>::format());
        }
        else if (instanceof (js_array, "Uint8Array"))
        {
           return new TypedArrayBuffer(js_array, py::format_descriptor<uint8_t>::format());
        }
        else if (instanceof (js_array, "Uint8ClampedArray"))
        {
           return new TypedArrayBuffer(js_array, py::format_descriptor<uint8_t>::format());
        }
        else if (instanceof (js_array, "Int16Array"))
        {
            return new TypedArrayBuffer(js_array, py::format_descriptor<int16_t>::format());
        }
        else if (instanceof (js_array, "Uint16Array"))
        {
            return new TypedArrayBuffer(js_array, py::format_descriptor<uint16_t>::format());
        }
        else if (instanceof (js_array, "Int32Array"))
        {
            return new TypedArrayBuffer(js_array, py::format_descriptor<int32_t>::format());
        }
        else if (instanceof (js_array, "Uint32Array"))
        {
            return new TypedArrayBuffer(js_array, py::format_descriptor<uint32_t>::format());
        }
        else if (instanceof (js_array, "Float32Array"))
        {
            return new TypedArrayBuffer(js_array, py::format_descriptor<float>::format());
        }
        else if (instanceof (js_array, "Float64Array"))
        {
            return new TypedArrayBuffer(js_array, py::format_descriptor<double>::format());
        }
        else if (instanceof (js_array, "BigInt64Array"))
        {
            return new TypedArrayBuffer(js_array, py::format_descriptor<int64_t>::format());
        }
        else if (instanceof (js_array, "BigUint64Array"))
        {
            return new TypedArrayBuffer(js_array, py::format_descriptor<uint64_t>::format());
        }
        else
        {
            throw pybind11::type_error("unknown array type");
        }
    }


    em::val bytes_to_js(char * binary_string, std::size_t length)
    {
        // get the length of the string
        em::val mem_view = em::val(em::typed_memory_view(length, binary_string));
        em::val mem_copy = em::val::global("Uint8Array").new_(mem_view);
        return mem_copy;
    }

    template <class T>
    em::val py_1d_buffer_to_typed_array_t(const std::size_t size,
                                          void* void_ptr,
                                          bool view,
                                          const std::string& js_cls_name)
    {
        T* ptr = static_cast<T*>(void_ptr);
        em::val mem_view = em::val(em::typed_memory_view(size, ptr));
        if (!view)
        {
            em::val mem_copy = em::val::global(js_cls_name.c_str()).new_(mem_view);
            return mem_copy;
        }
        return mem_view;
    }


    

    em::val py_1d_buffer_to_typed_array(py::buffer buffer, bool view)
    {
        /* Request a buffer descriptor from Python */
        py::buffer_info info = buffer.request();

        const auto format = info.format;


        if (info.ndim != 1)
        {
            throw std::runtime_error("Incompatible buffer dimension!");
        }



        // sizeof one element in bytes
        const auto itemsize = info.itemsize;
        const auto stride = (info.strides[0] / itemsize);
        if (stride != 1)
        {
            std::stringstream s;
            s << "only continous arrays are allowed but stride is " << stride << " raw stride "
              << info.strides[0] << " itemsize " << itemsize << " shape " << info.shape[0];
            throw std::runtime_error(s.str().c_str());
        }

        // shape
        const std::size_t size = info.shape[0];


        if (format == py::format_descriptor<float>::format())
        {
            return py_1d_buffer_to_typed_array_t<float>(size, info.ptr, view, "Float32Array");
        }
        else if (format == py::format_descriptor<double>::format())
        {
            return py_1d_buffer_to_typed_array_t<double>(size, info.ptr, view, "Float64Array");
        }
        else if (format == py::format_descriptor<uint8_t>::format())
        {
            return py_1d_buffer_to_typed_array_t<uint8_t>(size, info.ptr, view, "Uint8Array");
        }
        else if (format == py::format_descriptor<uint16_t>::format())
        {
            return py_1d_buffer_to_typed_array_t<uint16_t>(size, info.ptr, view, "Uint16Array");
        }
        else if (format == py::format_descriptor<uint32_t>::format() || format == "L")
        {
            return py_1d_buffer_to_typed_array_t<uint32_t>(size, info.ptr, view, "Uint32Array");
        }
        else if (format == py::format_descriptor<uint64_t>::format())
        {
            throw std::runtime_error(
                "uint64_t is not yet supported in pyjs since the stack is not yet compiled with WasmBigInt support");
        }
        else if (format == py::format_descriptor<int8_t>::format())
        {
            return py_1d_buffer_to_typed_array_t<int16_t>(size, info.ptr, view, "Int8Array");
        }
        else if (format == py::format_descriptor<int16_t>::format())
        {
            return py_1d_buffer_to_typed_array_t<int16_t>(size, info.ptr, view, "Int16Array");
        }
        else if (format == py::format_descriptor<int32_t>::format() || format == "l")
        {
            return py_1d_buffer_to_typed_array_t<int32_t>(size, info.ptr, view, "Int32Array");
        }
        else if (format == py::format_descriptor<int64_t>::format())
        {
            throw std::runtime_error(
                "int64_t is not yet supported in pyjs since the stack is not yet compiled with WasmBigInt support");
        }
        else
        {
            std::stringstream s;
            s << "pyjs error: an unknown format: occurred when converting np.ndarray to a JavaScript TypedArray: format="
              << format;
            throw std::runtime_error(s.str());
        }
    }

}
