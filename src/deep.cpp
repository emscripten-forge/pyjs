// Deep conversion: copying a whole structure (lists in dicts in lists ...)
// between the languages in ONE call across the border. This is what `to_py()`
// and `to_js()` use.
//
// The structure is written down as a "stream": a run of slots (slot.hpp) one
// after the other in memory, which the other side reads front to back. A
// container is a header slot (T_LIST / T_DICT / T_SET with the number of
// items) followed directly by its items. src/js/deep.ts explains the stream
// with an example; in short:
//
//     [1, "a", {"x": 2}]   ->   LIST 3, INT 1, STR "a", DICT 1, STR "x", INT 2
//
// A container that shows up a second time (shared, or containing itself) is
// written as `T_REF n`: "the n-th container of this stream again".
//
// The arrows name the direction the VALUE travels:
//
//   JS -> Python (to_py):  a JavaScript value becomes Python objects.
//                          deep.ts writes the stream, read_value() here reads it
//   Python -> JS (to_js):  a Python value becomes JavaScript objects.
//                          write_value() here writes it, deep.ts reads it
//
// As flow (the same as a diagram: docs/design.md):
//
//   to_py(proxy)   deep_to_py ---- 1 hop ----> deep.ts write(): walks the JS
//                                              value, writes the stream
//                  read_value() <-- stream --
//                  builds lists / dicts / sets
//   to_js(obj)     write_value(): walks the
//                  Python value, writes the
//                  stream ---------- 1 hop ---> deep.ts fromStream(): builds
//                                               Arrays / Objects / Sets / ...
//                  from_slot(result) <------- (a JSProxy of the new value)
#include "slot.hpp"

#include <emscripten.h>

#include <algorithm>
#include <cstdlib>
#include <cstring>
#include <unordered_map>
#include <vector>

// Write the JS object with handle `h` as stream (`depth` levels of
// containers, -1: all). Fills two slots at `out`:
//   out[0]   aux: the number of slots, num: the address of the first slot
//   out[1]   num: the address of the text block (see StreamReader)
// `fresh`: 1 if another stream is still being read (see deep_to_py)
// `limit`: at most that many levels of nesting, else return code 9 (RC_TOO_DEEP)
EM_JS(int, pyjs_js_to_py, (int h, int depth, int limit, int fresh, double out), {
    return pyjsCore.toPy(h, depth, limit, fresh, out);
});

// Build the JS value of the stream at `stream`; `out` gets it as ordinary slot.
EM_JS(int, pyjs_js_to_js, (double stream, double out), {
    return pyjsCore.toJs(stream, out);
});

// Copy the bytes of the typed array / ArrayBuffer with handle `h` to `ptr`,
// and release the handle: it was only needed for this copy. (Both in one
// function, because each call into JavaScript costs time.)
// `size`: the room at `ptr`. 0, or 1 if the buffer does not have that size
// any more (see bufferCopy in src/js/jsops.ts).
EM_JS(int, pyjs_js_buffer_take, (int h, double ptr, double size), {
    const rc = pyjsCore.bufferCopy(h, ptr, size);
    pyjsCore.free(h, 0);
    return rc;
});

// (defined in js_proxy.cpp)
extern "C" void pyjs_js_free(int h, int h2);

namespace pyjs
{
    namespace
    {
        // ------------------------------------------------------------------
        // JS -> Python: reading a stream
        // ------------------------------------------------------------------
        // How many levels of nesting a deep conversion follows (a list in a
        // list in a list ...). Beyond that: RecursionError.
        //
        // Both directions walk a structure by a function calling itself
        // once per level, in C and in JavaScript, and the call stack of the
        // browser is small and cannot grow: a WebKit worker gives up at
        // about 500 levels ("Maximum call stack size exceeded", which ends
        // the page). 200 is safe in every browser, and far more than data
        // has (deeply nested JSON has a few dozen levels).
        constexpr int MAX_NESTING = 200;

        // return code of pyjs_js_to_py for "nested too deeply" (Rc.TOO_DEEP
        // in src/js/jsops.ts)
        constexpr int RC_TOO_DEEP = 9;

        struct StreamReader
        {
            // the next slot to read
            Slot* next;
            // Where the texts of the stream are. JavaScript writes all strings
            // into one block of memory; a string slot holds the position of
            // its text inside that block (not its address, because the block
            // can move while JavaScript is still writing).
            const char* text;
            // The containers created so far, in the order of the stream: what
            // a T_REF slot refers to by number. Not owned: every container
            // here is kept alive by the structure being built.
            std::vector<PyObject*> containers;
        };

        // the str of a text slot of the stream
        inline PyObject* read_text(StreamReader& reader, Slot* slot)
        {
            // slot->num: the position in the text block, slot->aux: the length
            const char* utf8 = reader.text + static_cast<std::size_t>(slot->num);
            // "surrogatepass": a JS string may contain half a surrogate pair
            // (it is a sequence of 16 bit units, not of characters); keep
            // that instead of failing
            return PyUnicode_DecodeUTF8(utf8, slot->aux, "surrogatepass");
        }

        // A typed array / ArrayBuffer: a memoryview of a copy of its bytes,
        // with the item type of the typed array.
        // The slot: aux = a handle to the JS object, num = its size in
        // bytes, upper half of the tag = the item type as struct format
        // character ('d' for Float64Array, 'B' for bytes, ...).
        PyObject* read_buffer(Slot* slot)
        {
            const int handle = slot->aux;
            const char format[2] = { static_cast<char>(slot->tag >> 16), 0 };
            // The bytes are copied once, straight from JavaScript into the
            // new object (that is why they are not part of the stream). A
            // bytearray, not bytes: the result is a copy that belongs to the
            // caller, who may write to it (a memoryview of bytes is
            // read-only).
            PyObject* bytes = PyByteArray_FromStringAndSize(nullptr, static_cast<Py_ssize_t>(slot->num));
            if (bytes == nullptr)
            {
                // (no memory: the handle still has to be released)
                pyjs_js_free(handle, 0);
                return nullptr;
            }
            if (pyjs_js_buffer_take(handle, ptr_to_num(PyByteArray_AS_STRING(bytes)), slot->num) != 0)
            {
                Py_DECREF(bytes);
                PyErr_SetString(PyExc_BufferError,
                                "the JavaScript buffer changed its size (or was detached) while it was converted");
                return nullptr;
            }
            PyObject* view = PyMemoryView_FromObject(bytes);
            Py_DECREF(bytes);
            if (view == nullptr || format[0] == 'B')
            {
                return view;
            }
            // view.cast("d"): the same bytes seen as items of that type.
            // (The name "cast" is created once and kept: this runs for every
            // typed array, and building the string each time would cost more
            // than the call.)
            static PyObject* cast_name = PyUnicode_InternFromString("cast");
            PyObject* format_str = PyUnicode_FromStringAndSize(format, 1);
            PyObject* typed = nullptr;
            if (cast_name != nullptr && format_str != nullptr)
            {
                typed = PyObject_CallMethodOneArg(view, cast_name, format_str);
            }
            Py_XDECREF(format_str);
            Py_DECREF(view);
            return typed;
        }

        // The value of one slot that is no container (a new reference, or
        // nullptr with an exception set).
        PyObject* read_leaf(StreamReader& reader, Slot* slot)
        {
            switch (slot->tag & 0xff)
            {
                case T_REF:
                    // a container that was created earlier: the same object again
                    return Py_NewRef(reader.containers[slot->aux]);
                case T_STR:
                    return read_text(reader, slot);
                case T_BIGINT:
                {
                    // the digits as text; they become an int, then a JSBigInt
                    PyObject* digits = read_text(reader, slot);
                    PyObject* value = digits != nullptr ? PyLong_FromUnicodeObject(digits, 10) : nullptr;
                    Py_XDECREF(digits);
                    if (value == nullptr || hooks().bigint_type == nullptr)
                    {
                        return value;
                    }
                    PyObject* bigint = PyObject_CallOneArg(hooks().bigint_type, value);
                    Py_DECREF(value);
                    return bigint;
                }
                case T_BUFFER:
                    return read_buffer(slot);
                default:
                    // a simple value, or something that is not copied (a
                    // function, an instance of a class): the ordinary
                    // conversion, which gives a JSProxy for those
                    return from_slot(slot);
            }
        }

        // Read the next value of the stream; a container with all its items
        // (this function calls itself for them). A new reference, or nullptr
        // with a Python exception set.
        //
        // (The nesting is at most MAX_NESTING levels deep: the JavaScript
        // side refuses to write a deeper stream, see deep_to_py.)
        PyObject* read_value(StreamReader& reader)
        {
            Slot* slot = reader.next++;
            // (the upper bits of the tag carry flags / the buffer format)
            switch (slot->tag & 0xff)
            {
                case T_LIST:
                {
                    const Py_ssize_t n = slot->aux;
                    PyObject* list = PyList_New(n);
                    if (list == nullptr)
                    {
                        return nullptr;
                    }
                    // registered before its items are read: an item may be a
                    // T_REF to this very list (a list containing itself)
                    reader.containers.push_back(list);
                    for (Py_ssize_t i = 0; i < n; ++i)
                    {
                        PyObject* item = read_value(reader);
                        if (item == nullptr)
                        {
                            Py_DECREF(list);
                            return nullptr;
                        }
                        // (takes over the reference to `item`)
                        PyList_SET_ITEM(list, i, item);
                    }
                    return list;
                }
                case T_DICT:
                {
                    const Py_ssize_t n = slot->aux;
                    PyObject* dict = PyDict_New();
                    if (dict == nullptr)
                    {
                        return nullptr;
                    }
                    reader.containers.push_back(dict);
                    for (Py_ssize_t i = 0; i < n; ++i)
                    {
                        // an entry is two values in a row: key, then value
                        PyObject* key = read_value(reader);
                        PyObject* value = key != nullptr ? read_value(reader) : nullptr;
                        const bool ok = value != nullptr && PyDict_SetItem(dict, key, value) == 0;
                        Py_XDECREF(key);
                        Py_XDECREF(value);
                        if (!ok)
                        {
                            Py_DECREF(dict);
                            return nullptr;
                        }
                    }
                    return dict;
                }
                case T_SET:
                {
                    const Py_ssize_t n = slot->aux;
                    PyObject* set = PySet_New(nullptr);
                    if (set == nullptr)
                    {
                        return nullptr;
                    }
                    reader.containers.push_back(set);
                    for (Py_ssize_t i = 0; i < n; ++i)
                    {
                        PyObject* item = read_value(reader);
                        const bool ok = item != nullptr && PySet_Add(set, item) == 0;
                        Py_XDECREF(item);
                        if (!ok)
                        {
                            Py_DECREF(set);
                            return nullptr;
                        }
                    }
                    return set;
                }
                default:
                    return read_leaf(reader, slot);
            }
        }

        // ------------------------------------------------------------------
        // Python -> JS: writing a stream
        //
        // (A Python value goes to JavaScript: `to_js(obj)`. This side walks
        // the Python structure and writes the stream; deep.ts builds the
        // JavaScript objects from it.)
        // ------------------------------------------------------------------
        struct StreamWriter
        {
            // the stream
            std::vector<Slot> slots;
            // the containers written so far -> their number (for T_REF)
            std::unordered_map<PyObject*, int> seen;
            // Buffers whose memory slots of the stream point to: they must be
            // released (PyBuffer_Release) only after JavaScript has read the
            // stream.
            std::vector<Py_buffer> buffers;
            // Objects that must stay alive until JavaScript has read the
            // stream, for the same reason (the rows of a buffer that is no
            // flat block, see write_buffer), and the items of containers
            // (see `hold`).
            std::vector<PyObject*> keep;
            // The guard against structures nested too deeply (MAX_NESTING).
            // No counter is needed: `depth` already goes down by one per
            // level (from the caller's value, or from -1 for "all levels"),
            // `floor` is the start value minus the limit.
            int floor = 0;
        };

        // append a slot with a tag and the integer field `aux`
        inline void write_header(StreamWriter& writer, int32_t tag, int32_t aux)
        {
            Slot slot;
            slot.tag = tag;
            slot.aux = aux;
            slot.num = 0;
            writer.slots.push_back(slot);
        }

        // If `o` was written before: write a T_REF to it and return true.
        // Otherwise give it the next container number and return false.
        inline bool written_before(StreamWriter& writer, PyObject* o)
        {
            const auto found = writer.seen.find(o);
            if (found != writer.seen.end())
            {
                write_header(writer, T_REF, found->second);
                return true;
            }
            const int number = static_cast<int>(writer.seen.size());
            writer.seen.emplace(o, number);
            return false;
        }

        bool write_value(StreamWriter& writer, PyObject* o, int depth);

        // The function `name` of the python module pyjs.convert (a borrowed
        // reference, looked up once), or nullptr with an exception set. Used
        // for the rare checks that are much simpler to write in python.
        PyObject* convert_function(const char* name, PyObject*& cache)
        {
            if (cache == nullptr)
            {
                PyObject* module = PyImport_ImportModule("pyjs.convert");
                if (module == nullptr)
                {
                    return nullptr;
                }
                cache = PyObject_GetAttrString(module, name);
                Py_DECREF(module);
            }
            return cache;
        }

        // Would `o` become a NEW JavaScript container (list, tuple, dict,
        // set)? Such a value cannot be a key of a JavaScript object or an
        // item of a Set: the key would be a different object than the
        // Python one, and two equal Python keys two different JS objects.
        inline bool is_container(PyObject* o)
        {
            return PyList_Check(o) || PyTuple_Check(o) || PyDict_Check(o) || PyAnySet_Check(o);
        }

        // The keys of a dict that becomes a JavaScript object: no
        // containers, and no two keys with the same JavaScript property name
        // (1 and "1" are both the property "1"). Only dicts with keys other
        // than str need checking; that check is done by
        // pyjs.convert._check_dict_keys. False with ConversionError set.
        bool check_dict_keys(PyObject* dict)
        {
            PyObject* key;
            PyObject* value;
            Py_ssize_t position = 0;
            while (PyDict_Next(dict, &position, &key, &value))
            {
                if (!PyUnicode_CheckExact(key))
                {
                    static PyObject* check = nullptr;
                    PyObject* function = convert_function("_check_dict_keys", check);
                    PyObject* ret = function != nullptr ? PyObject_CallOneArg(function, dict) : nullptr;
                    Py_XDECREF(ret);
                    return ret != nullptr;
                }
            }
            return true;
        }

        // An item of a set that becomes a JavaScript Set: no containers (see
        // is_container). False with ConversionError set.
        bool check_set_item(PyObject* item)
        {
            if (!is_container(item))
            {
                return true;
            }
            static PyObject* check = nullptr;
            PyObject* function = convert_function("_check_key", check);
            PyObject* target = PyUnicode_FromString("Set");
            PyObject* ret = function != nullptr && target != nullptr
                                ? PyObject_CallFunctionObjArgs(function, item, target, nullptr)
                                : nullptr;
            Py_XDECREF(target);
            Py_XDECREF(ret);
            return ret != nullptr;
        }

        // A buffer (bytes, bytearray, a numpy array, ...): JavaScript makes a
        // typed array with a copy of its items. The slot: num = the address
        // of the memory, aux = the number of items, upper half of the tag =
        // the item type as struct format character.
        bool write_buffer(StreamWriter& writer, PyObject* o, int depth)
        {
            Py_buffer view;
            const bool flat = PyObject_GetBuffer(o, &view, PyBUF_FORMAT | PyBUF_C_CONTIGUOUS) == 0;
            const bool multi_dimensional = flat && view.ndim > 1;
            if (multi_dimensional)
            {
                PyBuffer_Release(&view);
            }
            if (!flat || multi_dimensional)
            {
                // A buffer that is no flat block of items: several
                // dimensions, or scattered in memory (strides, "suboffsets"
                // of PIL style images). Nested lists with one flat buffer
                // per row (pyjs.convert._buffer_rows), which become nested
                // Arrays of typed arrays.
                PyErr_Clear();
                static PyObject* rows = nullptr;
                PyObject* function = convert_function("_buffer_rows", rows);
                PyObject* items = function != nullptr ? PyObject_CallOneArg(function, o) : nullptr;
                if (items == nullptr)
                {
                    return false;
                }
                // (the lists must outlive the stream: their items are
                // referenced by slots)
                writer.keep.push_back(items);
                return write_value(writer, items, depth);
            }
            // (no format: unsigned bytes; a byte order / size prefix is skipped)
            const char* format = view.format != nullptr ? view.format : "B";
            if (*format == '@' || *format == '=' || *format == '<')
            {
                ++format;
            }
            // only flat arrays of one number type have a typed array
            if (format[0] == 0 || format[1] != 0 || std::strchr("bBc?hHiIlLqQfd", format[0]) == nullptr)
            {
                PyErr_Format(PyExc_TypeError,
                             "to_js: a contiguous 1d buffer of numbers is required (ndim %d, format '%s')",
                             view.ndim,
                             format);
                PyBuffer_Release(&view);
                return false;
            }
            Slot slot;
            // (js_buffer_format: a C long as the fixed size type, see slot.hpp)
            slot.tag = T_BUFFER | (static_cast<int32_t>(js_buffer_format(format[0], view.itemsize)) << 16);
            slot.aux = static_cast<int32_t>(view.len / view.itemsize);
            slot.num = ptr_to_num(view.buf);
            writer.slots.push_back(slot);
            // released after the call into JavaScript
            writer.buffers.push_back(view);
            return true;
        }

        // Keep `o` (an item of a container that is being written) alive until
        // JavaScript has read the stream; returns `o`.
        //
        // The container normally does that. But writing an item can run
        // Python code (see write_value), and that code may take items out of
        // the container: the item being written, or one written earlier
        // whose slot points into it (the text of a str). Numbers, bools and
        // None need nothing: their slots hold the value itself, and writing
        // them runs no code.
        inline PyObject* hold(StreamWriter& writer, PyObject* o)
        {
            PyTypeObject* type = Py_TYPE(o);
            if (o != Py_None && type != &PyLong_Type && type != &PyFloat_Type && type != &PyBool_Type)
            {
                writer.keep.push_back(Py_NewRef(o));
            }
            return o;
        }

        // "the container changed while it was converted": the number of
        // items announced in its header can no longer be kept
        inline bool changed_size(const char* what)
        {
            PyErr_Format(PyExc_RuntimeError, "to_js: %s changed size during the conversion", what);
            return false;
        }

        // Append `o` to the stream, containers `depth` levels deep (-1: all).
        // False with a Python exception set.
        //
        //   list, tuple                    -> Array (other sequences: proxy)
        //   dict                           -> Object
        //   set, frozenset                 -> Set
        //   buffers                        -> typed array
        //   None, bool, int, float, str, JSProxy   -> as always (to_slot)
        //   anything else                  -> stays Python: a proxy
        //
        // The function calls itself for the items of a container, at most
        // MAX_NESTING levels deep (RecursionError beyond, see there).
        //
        // Converting an item can run Python code (the `__buffer__` of an
        // object, the check of dict keys, a `__del__` when the garbage
        // collector happens to run, ...), which could change the container
        // that is being walked. So nothing is remembered that such a change
        // would make invalid: a list is asked for its size and its item
        // every time, the items are kept alive (`hold`), and a container
        // that no longer has the number of items of its header is an error
        // (RuntimeError, as Python raises it for a dict changed during
        // iteration).
        bool write_value(StreamWriter& writer, PyObject* o, int depth)
        {
            PyTypeObject* type = Py_TYPE(o);
            // The simple values first: most items of most structures are one
            // of these, and they need nothing but their slot.
            const bool simple = o == Py_None || type == &PyLong_Type || type == &PyUnicode_Type
                                || type == &PyFloat_Type || type == &PyBool_Type;
            if (!simple && depth != 0)
            {
                if (depth < writer.floor)
                {
                    // nested too deeply, see StreamWriter::floor
                    PyErr_Format(PyExc_RecursionError,
                                 "to_js: the object is nested more than %d levels deep",
                                 MAX_NESTING);
                    return false;
                }
                if (PyList_Check(o) || PyTuple_Check(o))
                {
                    if (written_before(writer, o))
                    {
                        return true;
                    }
                    const Py_ssize_t n = PySequence_Fast_GET_SIZE(o);
                    write_header(writer, T_LIST, static_cast<int32_t>(n));
                    for (Py_ssize_t i = 0; i < n; ++i)
                    {
                        if (i >= PySequence_Fast_GET_SIZE(o))
                        {
                            return changed_size("a list");
                        }
                        // (list and tuple both keep their items in a plain array)
                        if (!write_value(writer, hold(writer, PySequence_Fast_ITEMS(o)[i]), depth - 1))
                        {
                            return false;
                        }
                    }
                    return true;
                }
                if (PyDict_Check(o))
                {
                    if (written_before(writer, o))
                    {
                        return true;
                    }
                    if (!check_dict_keys(o))
                    {
                        return false;
                    }
                    const Py_ssize_t n = PyDict_GET_SIZE(o);
                    write_header(writer, T_DICT, static_cast<int32_t>(n));
                    PyObject* key;
                    PyObject* value;
                    Py_ssize_t position = 0;
                    Py_ssize_t written = 0;
                    while (PyDict_Next(o, &position, &key, &value))
                    {
                        if (written == n)
                        {
                            return changed_size("a dict");
                        }
                        written += 1;
                        hold(writer, key);
                        hold(writer, value);
                        if (!write_value(writer, key, depth - 1) || !write_value(writer, value, depth - 1))
                        {
                            return false;
                        }
                        if (PyDict_GET_SIZE(o) != n)
                        {
                            return changed_size("a dict");
                        }
                    }
                    return written == n || changed_size("a dict");
                }
                if (PyAnySet_Check(o))
                {
                    if (written_before(writer, o))
                    {
                        return true;
                    }
                    const Py_ssize_t n = PySet_GET_SIZE(o);
                    write_header(writer, T_SET, static_cast<int32_t>(n));
                    PyObject* iterator = PyObject_GetIter(o);
                    if (iterator == nullptr)
                    {
                        return false;
                    }
                    bool ok = true;
                    Py_ssize_t written = 0;
                    PyObject* item;
                    // (the iterator of a set raises itself when the set
                    // changed size)
                    while (ok && (item = PyIter_Next(iterator)) != nullptr)
                    {
                        ok = written < n ? check_set_item(item) && write_value(writer, hold(writer, item), depth - 1)
                                         : changed_size("a set");
                        written += 1;
                        Py_DECREF(item);
                    }
                    Py_DECREF(iterator);
                    return ok && !PyErr_Occurred() && (written == n || changed_size("a set"));
                }
                // str, int and float subclasses, JSProxy: simple values too
                if (!PyUnicode_Check(o) && !PyLong_Check(o) && !PyFloat_Check(o) && js_proxy_handle(o) == 0)
                {
                    // bytes, bytearray, memoryview, numpy arrays, ...
                    if (PyObject_CheckBuffer(o))
                    {
                        return write_buffer(writer, o, depth);
                    }
                }
                // Other sequences (range, deque, user classes registered as
                // Sequence, ...) are NOT copied: like any other Python
                // object they become a proxy (below). Only lists and tuples
                // become Arrays, as in pyodide.
            }
            // A simple value, a JSProxy, an object that is not converted, or
            // a container below the depth limit: the ordinary conversion. For
            // a Python object that means: JavaScript gets a proxy of it.
            Slot slot;
            if (!to_slot(o, &slot))
            {
                return false;
            }
            writer.slots.push_back(slot);
            return true;
        }

        // Give back what the slots of a stream own, when the stream never
        // reached JavaScript (writing it failed half way).
        void release_stream(std::vector<Slot>& slots)
        {
            for (Slot& slot : slots)
            {
                if (slot.tag == T_PY)
                {
                    // the reference meant for the PyProxy
                    Py_DECREF(num_to_ptr<PyObject>(slot.num));
                }
                else if (slot.tag == (T_BIGINT | T_OWNED))
                {
                    // the digits of a big int (see bigint_to_slot)
                    std::free(num_to_ptr<char>(slot.num));
                }
            }
        }
    }

    // to_py(value): a copy of a JavaScript value as Python objects.
    //
    // Why the argument is a PyObject: this is called from Python
    // (`pyjs.to_py(x)` -> `pyjs_core.to_py` in module.cpp), and everything
    // Python passes is a Python object. The JavaScript value it is about
    // arrives as its stand-in in Python, a JSProxy (yes: "a JavaScript thing
    // inside"). Its handle says which JavaScript object to convert. Anything
    // else (a str, an int, a list, ...) is already a Python value: returned as
    // it is.
    //
    // The steps:
    //   1. ONE call into JavaScript (pyjs_js_to_py -> deep.ts): JavaScript
    //      walks its object and writes the whole structure as stream into
    //      memory, `depth` levels deep
    //   2. read_value() reads the stream front to back here and builds the
    //      Python objects (lists, dicts, sets, memoryviews, strings, ...)
    PyObject* deep_to_py(PyObject* proxy, int depth)
    {
        const int handle = js_proxy_handle(proxy);
        if (handle == 0)
        {
            // not a JS object: nothing to convert
            return Py_NewRef(proxy);
        }
        // How many streams are being read right now (this function, further
        // up the call stack). JavaScript writes a stream into memory it
        // reuses for the next conversion. Reading a stream runs Python code
        // (the `__hash__` of a dict key, the constructor of an exception,
        // ...), and that code may convert something else: then JavaScript
        // must leave the memory of the stream being read alone (`fresh`).
        static int reading = 0;
        Slot out[2];
        // (any negative depth means "all levels")
        const int rc = pyjs_js_to_py(handle, depth < 0 ? -1 : depth, MAX_NESTING, reading > 0 ? 1 : 0, ptr_to_num(out));
        if (rc == RC_TOO_DEEP)
        {
            PyErr_Format(PyExc_RecursionError, "to_py: the object is nested more than %d levels deep", MAX_NESTING);
            return nullptr;
        }
        if (rc != 0)
        {
            raise_from_slot(out);
            return nullptr;
        }
        StreamReader reader;
        reader.next = num_to_ptr<Slot>(out[0].num);
        reader.text = num_to_ptr<char>(out[1].num);
        reading += 1;
        PyObject* value = read_value(reader);
        reading -= 1;
        if (value == nullptr)
        {
            // Reading stopped at an error (e.g. a key Python cannot hash):
            // the slots after that point were never read, and the JS
            // objects they hand over (handles) would never be released.
            Slot* end = num_to_ptr<Slot>(out[0].num) + out[0].aux;
            discard_js_slots(reader.next, end - reader.next);
        }
        return value;
    }

    // to_js(obj): a copy of a Python value as JavaScript objects, the other
    // direction: write_value() walks `obj` here and writes the stream, then
    // ONE call into JavaScript (pyjs_js_to_js -> deep.ts) builds the
    // JavaScript objects from it. The result comes back as an ordinary slot:
    // a JSProxy of the new JavaScript value (or the value itself if it is a
    // primitive).
    PyObject* deep_to_js(PyObject* obj, int depth)
    {
        StreamWriter writer;
        // (any negative depth means "all levels")
        depth = depth < 0 ? -1 : depth;
        writer.floor = depth - MAX_NESTING;
        const bool written = write_value(writer, obj, depth);

        PyObject* result = nullptr;
        if (written)
        {
            Slot out;
            const int rc = pyjs_js_to_js(ptr_to_num(writer.slots.data()), ptr_to_num(&out));
            if (rc != 0)
            {
                raise_from_slot(&out);
            }
            else
            {
                result = from_slot(&out);
            }
        }
        else
        {
            release_stream(writer.slots);
        }
        // JavaScript has made its copies: what the stream pointed to is free again
        for (Py_buffer& view : writer.buffers)
        {
            PyBuffer_Release(&view);
        }
        for (PyObject* o : writer.keep)
        {
            Py_DECREF(o);
        }
        return result;
    }
}
