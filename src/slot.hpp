// The wire format between Python (wasm) and JavaScript.
//
// THE PROBLEM. Python runs inside WebAssembly. Wasm and JavaScript can only
// pass plain numbers to each other, and every call across that border costs
// time. A naive bridge makes several such calls per value ("is it a string?",
// "how long?", "give me the bytes", ...).
//
// THE IDEA. JavaScript can read and write the wasm memory directly. So a
// value is written into memory in a fixed 16 byte layout, a "slot" (struct
// Slot below), and only its address is passed. One call across the border is
// then enough for a whole operation: the caller writes the argument slots,
// makes the call, and reads the result slot afterwards.
//
//   Python -> JS   to_slot() fills slots here, JS reads them   (decode)
//   JS -> Python   JS fills slots (encode), from_slot() reads them here
//
// The JS side is src/js/codec.ts, with a longer explanation and examples.
// The tag / flag numbers must be identical there.
#pragma once

#include <Python.h>

#include <cstdint>

namespace pyjs
{
    // slot.tag
    enum Tag : int32_t
    {
        T_UNDEF = 0,   // undefined <-> None
        T_NULL = 1,    // null <-> jsnull
        T_FALSE = 2,
        T_TRUE = 3,
        T_INT = 4,     // num: an integer valued double (JS -> Python only)
        T_FLOAT = 5,   // num
        T_STR = 6,     // num: pointer to utf8, aux: length in bytes
        T_BIGINT = 7,  // like T_STR: the decimal digits
        T_JS = 8,      // aux: handle of a JS object, a: its flags, b: handle of `this`
        T_PY = 9,      // num: PyObject*, aux: its flags
        T_ERROR = 10,  // aux: handle of the thrown JS value, or num: the Python exception
        // only inside the slot streams of a deep conversion (deep.cpp)
        T_LIST = 11,   // aux: number of items, which follow
        T_DICT = 12,   // aux: number of entries; key, value, key, value ... follow
        T_SET = 13,    // aux: number of items, which follow
        T_REF = 14,    // aux: index of a container that came earlier in the stream
        T_BUFFER = 15, // a buffer / typed array, see deep.cpp
    };

    // or-ed to T_STR / T_BIGINT: the receiver frees the buffer
    constexpr int32_t T_OWNED = 0x100;

    // what a JS object can do (computed in JS when a handle is created): each
    // set of flags is one subtype of JSProxy
    enum JsFlag : int32_t
    {
        JS_CALLABLE = 1 << 0,
        JS_LENGTH = 1 << 1,    // length or size
        JS_CONTAINS = 1 << 2,  // has() or includes()
        JS_ITERABLE = 1 << 3,
        JS_ITERATOR = 1 << 4,  // next()
        JS_AWAITABLE = 1 << 5, // then()
        JS_GETITEM = 1 << 6,   // obj[key]: an Array / typed array, or it has get()
        JS_SETITEM = 1 << 7,   // obj[key] = value: an Array / typed array, or it has set()
        JS_FLAG_END = 1 << 8,
    };

    // what a Python object can do (computed in C when it is passed to JS)
    enum PyFlag : int32_t
    {
        PY_CALLABLE = 1 << 0,
        PY_AWAITABLE = 1 << 1,
        PY_ITERABLE = 1 << 2,
        PY_ITERATOR = 1 << 3,
    };

    struct Slot
    {
        int32_t tag;
        int32_t aux;
        union
        {
            double num;
            struct
            {
                int32_t a;
                int32_t b;
            } i;
        };
    };
    static_assert(sizeof(Slot) == 16, "the JS side reads 16 byte slots");

    // pointers cross the boundary as double (exact up to 2^53): the same code
    // for wasm32 and wasm64, no BigInt on the JS side
    inline double ptr_to_num(const void* p)
    {
        return static_cast<double>(reinterpret_cast<std::uintptr_t>(p));
    }

    template <class T>
    T* num_to_ptr(double num)
    {
        return reinterpret_cast<T*>(static_cast<std::uintptr_t>(num));
    }

    // Python -> slot (implicit conversion). `o` is borrowed; a T_PY slot
    // carries a new reference, owned by the PyProxy JS creates for it.
    // Returns false with a Python exception set.
    bool to_slot(PyObject* o, Slot* slot);

    // slot -> Python (implicit conversion), a new reference. A T_ERROR slot
    // raises: nullptr with the Python exception set.
    PyObject* from_slot(Slot* slot);

    // a JSProxy for a handle (owned by the proxy) with its flags
    PyObject* js_proxy_new(int handle, int flags, int this_handle);

    // the handle of a JSProxy, 0 for other objects
    int js_proxy_handle(PyObject* o);

    // create the JSProxy types; false with a Python exception set
    bool js_proxy_init(PyObject* module);

    // JSProxy of globalThis (0) / the emscripten Module (1)
    PyObject* js_global(int which);

    // a JSProxy of a PyProxy of `obj` (not unwrapped when it comes back to
    // Python, to be destroyed by its user). Objects that convert to JS values
    // (str, int, JSProxy, ...) have no proxy: TypeError if `always`, else
    // `obj` itself is returned.
    PyObject* create_proxy(PyObject* obj, bool always);

    // block until the promise (a JSProxy) settles: its value, or raises (JSPI)
    PyObject* run_sync(PyObject* promise);

    // raise the Python exception for a T_ERROR slot (a JS value was thrown)
    void raise_from_slot(Slot* slot);

    // Deep conversions (deep.cpp), each one hop for the whole structure.
    // `depth`: how many levels of containers are converted, -1 for all.
    //   deep_to_py: a copy of the JS value behind `proxy` as Python objects
    //   deep_to_js: a copy of `obj` as JS value (a JSProxy of it)
    // Both return a new reference, or nullptr with a Python exception set.
    PyObject* deep_to_py(PyObject* proxy, int depth);
    PyObject* deep_to_js(PyObject* obj, int depth);

    // the Python callables / objects the core needs (set by the pyjs module)
    struct Hooks
    {
        PyObject* raise_js_error = nullptr;  // (JSProxy of the thrown value) -> raises
        PyObject* format_exception = nullptr;  // (exception) -> str
        PyObject* await_js = nullptr;  // (JSProxy) -> iterator (for __await__)
        PyObject* jsnull = nullptr;  // the object JS null converts to
        PyObject* bigint_type = nullptr;  // int subclass JS BigInt converts to
        PyObject* sequence_abc = nullptr;  // collections.abc.Sequence (to_js: what becomes an Array)
        // (JSProxy, depth, default_converter) -> the converted value: to_py
        // with a converter function, which Python code does step by step
        PyObject* to_py_with_converter = nullptr;
    };
    Hooks& hooks();
}
