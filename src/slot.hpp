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
        // The following do not add operations in C: they select Python
        // classes with extra methods (append(), keys(), send(), ...) that
        // the proxy type derives from, see Hooks::proxy_mixins.
        JS_ARRAY = 1 << 8,            // an Array
        JS_BUFFER = 1 << 9,           // a typed array, DataView or ArrayBuffer
        JS_MAP = 1 << 10,             // like a Map: get(), has(), size, iterable
        JS_GENERATOR = 1 << 11,       // an iterator with return() and throw()
        JS_ASYNC_ITERABLE = 1 << 12,  // has [Symbol.asyncIterator]
        JS_ASYNC_ITERATOR = 1 << 13,  // next() returns promises
        JS_ERROR = 1 << 14,           // an Error: python gets a JSException
        JS_DOUBLE_PROXY = 1 << 15,    // a PyProxy made by create_proxy (JSDoubleProxy)
        JS_FLAG_END = 1 << 16,
    };

    // what a Python object can do (computed in C when it is passed to JS)
    enum PyFlag : int32_t
    {
        PY_CALLABLE = 1 << 0,
        PY_AWAITABLE = 1 << 1,
        PY_ITERABLE = 1 << 2,
        PY_ITERATOR = 1 << 3,
        PY_SIZED = 1 << 4,  // has len()
        PY_GENERATOR = 1 << 5,  // a generator (send / throw / close)
    };

    // One value crossing the border, 16 bytes:
    //
    //   byte  0..3   tag   int32   what kind of value (Tag above)
    //   byte  4..7   aux   int32   a small extra number, depends on the tag:
    //                              length of a string, handle of a JS object,
    //                              flags of a Python object, ...
    //   byte  8..15  num   double  the value itself: a number, or an address
    //                OR  a, b      two int32 for the kinds that need two more
    //                              small numbers instead (T_JS: its flags and
    //                              the handle of its `this`)
    //
    // Examples:
    //   3.5             { tag: T_FLOAT, num: 3.5 }
    //   "hi"            { tag: T_STR,   aux: 2 (bytes), num: address of "hi" }
    //   a JS function   { tag: T_JS,    aux: 17 (its handle), a: JS_CALLABLE,
    //                     b: 0 (no `this`) }
    //   a Python list   { tag: T_PY,    aux: its PyFlags, num: its PyObject* }
    // (Which field means what for each tag: the comments of enum Tag.)
    //
    // Why a union for the last 8 bytes: a value needs EITHER one double OR
    // two small ints there, never both. Sharing the bytes keeps every slot at
    // 16 bytes, so an array of argument slots is a plain array and slot i is
    // at `base + 16 * i`.
    //
    // Why int32_t (and not int / size_t): JavaScript reads the slot through
    // typed-array views of the wasm memory, HEAP32 (int32 items) and HEAPF64
    // (float64 items). Fixed 32 bit fields map 1:1 onto HEAP32 items on wasm32
    // AND wasm64 (where int is still 32 bit, but size_t / pointers are 64).
    // `num` at byte 8 is 8-aligned, as HEAPF64 needs. Handles are indices
    // into a JS array (src/js/codec.ts), small numbers: 32 bit is plenty.
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

    // The struct format character of buffer items as JavaScript understands
    // it (it picks the typed array class by this character, src/js/jsops.ts
    // and src/js/deep.ts). Only "l" / "L" (C long) need translating: a long
    // has 32 bits on wasm32 but 64 on wasm64 (numpy's int64 has format "l"
    // there), so it becomes the character of the fixed size type: "i" / "I"
    // or "q" / "Q". JavaScript does not know the size of a C long; this side
    // does.
    inline char js_buffer_format(char format)
    {
        if (format == 'l')
        {
            return sizeof(long) == 4 ? 'i' : 'q';
        }
        if (format == 'L')
        {
            return sizeof(long) == 4 ? 'I' : 'Q';
        }
        return format;
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

    // Forget the proxy types created so far, so that they are created again
    // (with the mixin classes of Hooks::proxy_mixins) when next needed.
    // Called when the hooks are set: the Python code providing the mixins
    // itself uses a few proxies before it can register them, and the types
    // made for those have no mixins. Proxies that exist keep their type.
    void js_proxy_forget_types();

    // JSProxy of globalThis (0) / the emscripten Module (1)
    PyObject* js_global(int which);

    // A JSProxy of a lasting PyProxy of `obj` (destroyed by its user).
    // `roundtrip`: when the PyProxy comes back to python from JavaScript,
    // python gets this JSProxy again (a "double proxy") instead of `obj`.
    // Objects that convert to JS values (str, int, JSProxy, ...) have no
    // proxy: TypeError if `always`, else `obj` itself is returned.
    PyObject* create_proxy(PyObject* obj, bool always, bool roundtrip);

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

    // Hooks: Python functions / classes that this C++ core calls.
    //
    // WHY. Some parts of the bridge are much easier to write in Python than
    // in C++: the exception class JSException and how it is built, awaiting a
    // JS promise with asyncio, the methods of array / map proxies, ... They
    // live in the Python package `pyjs` (module/pyjs/). But the dependency
    // goes the other way: `pyjs` imports this core (`pyjs_core`), so the
    // core cannot import `pyjs` (and must not: an embedder may use the core
    // without the package).
    //
    // HOW. The core keeps a slot for each such Python object, initially empty
    // (nullptr). When `pyjs` is imported it hands them over once:
    // `pyjs_core.set_hooks(...)` in module/pyjs/__init__.py (defined in
    // src/module.cpp). From then on the core calls them like callbacks, e.g.
    // `raise_js_error(proxy)` when JavaScript threw. ("Hook": a place where
    // other code hooks itself in.)
    //
    // Before that (only while the package itself is being imported) a hook
    // is nullptr and the core does something simple instead (e.g. a plain
    // RuntimeError for a JS error); every use checks for nullptr.
    struct Hooks
    {
        PyObject* raise_js_error = nullptr;  // (JSProxy of the thrown value) -> raises
        PyObject* format_exception = nullptr;  // (exception) -> str
        PyObject* await_js = nullptr;  // (JSProxy) -> iterator (for __await__)
        PyObject* jsnull = nullptr;  // the object JS null converts to
        PyObject* bigint_type = nullptr;  // int subclass JS BigInt converts to
        // (JSProxy, depth, default_converter) -> the converted value: to_py
        // with a converter function, which Python code does step by step
        PyObject* to_py_with_converter = nullptr;
        // (flags: int) -> tuple of Python classes: the extra base classes of
        // the proxy type for JS objects with these JsFlags. They hold the
        // methods that are easier to write in Python than in C, e.g.
        // append() / pop() for arrays (pyjs/_proxy_types.py).
        PyObject* proxy_mixins = nullptr;
        // (coroutine) -> task: start a coroutine that a Python function
        // called from JavaScript returned (asyncio.ensure_future), see
        // `call` in py_entry.cpp
        PyObject* schedule_coroutine = nullptr;
        // the class JSException: a JavaScript Error reaching python is an
        // instance of it (created as `JSException(proxy_of_the_error)`), and
        // such an instance passed back to JavaScript is the Error again
        PyObject* jsexception_type = nullptr;
    };
    Hooks& hooks();
}
