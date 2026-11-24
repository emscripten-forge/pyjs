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
//   JS -> Python (to_py):  deep.ts writes the stream, read_value() here reads it
//   Python -> JS (to_js):  write_value() here writes it, deep.ts reads it
#include "slot.hpp"

#include <emscripten.h>

#include <cstdlib>
#include <cstring>
#include <unordered_map>
#include <vector>

// Write the JS object with handle `h` as stream (`depth` levels of
// containers, -1: all). Fills two slots at `out`:
//   out[0]   aux: the number of slots, num: the address of the first slot
//   out[1]   num: the address of the text block (see StreamReader)
EM_JS(int, pyjs_js_to_py, (int h, int depth, double out), {
    return pj.toPy(h, depth, out);
});

// Build the JS value of the stream at `stream`; `out` gets it as ordinary slot.
EM_JS(int, pyjs_js_to_js, (double stream, double out), {
    return pj.toJs(stream, out);
});

// Copy the bytes of the typed array / ArrayBuffer with handle `h` to `ptr`,
// and release the handle: it was only needed for this copy. (Both in one
// function, because each call into JavaScript costs time.)
EM_JS(void, pyjs_js_buffer_take, (int h, double ptr), {
    pj.bufferCopy(h, ptr);
    pj.free(h, 0);
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
            // new bytes object (that is why they are not part of the stream).
            PyObject* bytes = PyBytes_FromStringAndSize(nullptr, static_cast<Py_ssize_t>(slot->num));
            if (bytes == nullptr)
            {
                // (no memory: the handle still has to be released)
                pyjs_js_free(handle, 0);
                return nullptr;
            }
            pyjs_js_buffer_take(handle, ptr_to_num(PyBytes_AS_STRING(bytes)));
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

        // Read the next value of the stream; a container with all its items
        // (this function calls itself for them). A new reference, or nullptr
        // with a Python exception set.
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

        // ------------------------------------------------------------------
        // Python -> JS: writing a stream
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
            // stream, for the same reason (the item lists of generic
            // sequences).
            std::vector<PyObject*> keep;
            // collections.abc.Sequence, or nullptr
            PyObject* sequence_abc;
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

        // a T_LIST header followed by the `n` objects at `items`
        bool write_items(StreamWriter& writer, PyObject** items, Py_ssize_t n, int depth)
        {
            write_header(writer, T_LIST, static_cast<int32_t>(n));
            for (Py_ssize_t i = 0; i < n; ++i)
            {
                if (!write_value(writer, items[i], depth - 1))
                {
                    return false;
                }
            }
            return true;
        }

        // A buffer (bytes, bytearray, a numpy array, ...): JavaScript makes a
        // typed array with a copy of its items. The slot: num = the address
        // of the memory, aux = the number of items, upper half of the tag =
        // the item type as struct format character.
        bool write_buffer(StreamWriter& writer, PyObject* o)
        {
            Py_buffer view;
            if (PyObject_GetBuffer(o, &view, PyBUF_FORMAT | PyBUF_C_CONTIGUOUS) != 0)
            {
                return false;
            }
            // (no format: unsigned bytes; a byte order / size prefix is skipped)
            const char* format = view.format != nullptr ? view.format : "B";
            if (*format == '@' || *format == '=' || *format == '<')
            {
                ++format;
            }
            // only flat arrays of one number type have a typed array
            if (view.ndim > 1 || format[0] == 0 || format[1] != 0 || std::strchr("bBc?hHiIlLqQfd", format[0]) == nullptr)
            {
                PyErr_Format(PyExc_TypeError,
                             "to_js: a contiguous 1d buffer of numbers is required (ndim %d, format '%s')",
                             view.ndim,
                             format);
                PyBuffer_Release(&view);
                return false;
            }
            Slot slot;
            slot.tag = T_BUFFER | (static_cast<int32_t>(format[0]) << 16);
            slot.aux = static_cast<int32_t>(view.len / view.itemsize);
            slot.num = ptr_to_num(view.buf);
            writer.slots.push_back(slot);
            // released after the call into JavaScript
            writer.buffers.push_back(view);
            return true;
        }

        // Append `o` to the stream, containers `depth` levels deep (-1: all).
        // False with a Python exception set.
        //
        //   list, tuple, other sequences   -> Array
        //   dict                           -> Object
        //   set, frozenset                 -> Set
        //   buffers                        -> typed array
        //   None, bool, int, float, str, JSProxy   -> as always (to_slot)
        //   anything else                  -> stays Python: a proxy
        bool write_value(StreamWriter& writer, PyObject* o, int depth)
        {
            PyTypeObject* type = Py_TYPE(o);
            // The simple values first: most items of most structures are one
            // of these, and they need nothing but their slot.
            const bool simple = o == Py_None || type == &PyLong_Type || type == &PyUnicode_Type
                                || type == &PyFloat_Type || type == &PyBool_Type;
            if (!simple && depth != 0)
            {
                if (PyList_Check(o) || PyTuple_Check(o))
                {
                    if (written_before(writer, o))
                    {
                        return true;
                    }
                    // (list and tuple both keep their items in a plain array)
                    return write_items(writer, PySequence_Fast_ITEMS(o), PySequence_Fast_GET_SIZE(o), depth);
                }
                if (PyDict_Check(o))
                {
                    if (written_before(writer, o))
                    {
                        return true;
                    }
                    write_header(writer, T_DICT, static_cast<int32_t>(PyDict_GET_SIZE(o)));
                    PyObject* key;
                    PyObject* value;
                    Py_ssize_t position = 0;
                    while (PyDict_Next(o, &position, &key, &value))
                    {
                        if (!write_value(writer, key, depth - 1) || !write_value(writer, value, depth - 1))
                        {
                            return false;
                        }
                    }
                    return true;
                }
                if (PyAnySet_Check(o))
                {
                    if (written_before(writer, o))
                    {
                        return true;
                    }
                    write_header(writer, T_SET, static_cast<int32_t>(PySet_GET_SIZE(o)));
                    PyObject* iterator = PyObject_GetIter(o);
                    if (iterator == nullptr)
                    {
                        return false;
                    }
                    bool ok = true;
                    PyObject* item;
                    while (ok && (item = PyIter_Next(iterator)) != nullptr)
                    {
                        ok = write_value(writer, item, depth - 1);
                        // (the set keeps the item alive)
                        Py_DECREF(item);
                    }
                    Py_DECREF(iterator);
                    return ok && !PyErr_Occurred();
                }
                // str, int and float subclasses, JSProxy: simple values too
                if (!PyUnicode_Check(o) && !PyLong_Check(o) && !PyFloat_Check(o) && js_proxy_handle(o) == 0)
                {
                    // bytes, bytearray, memoryview, numpy arrays, ...
                    // (before the sequence check: bytes is a sequence too)
                    if (PyObject_CheckBuffer(o))
                    {
                        return write_buffer(writer, o);
                    }
                    // any other sequence (range, deque, user classes
                    // registered as Sequence, ...): its items as a list
                    if (writer.sequence_abc != nullptr)
                    {
                        const int is_sequence = PyObject_IsInstance(o, writer.sequence_abc);
                        if (is_sequence < 0)
                        {
                            return false;
                        }
                        if (is_sequence == 1)
                        {
                            if (written_before(writer, o))
                            {
                                return true;
                            }
                            PyObject* items = PySequence_Fast(o, "to_js: cannot read the items of a sequence");
                            if (items == nullptr)
                            {
                                return false;
                            }
                            // slots of the stream will point into the items
                            writer.keep.push_back(items);
                            return write_items(writer, PySequence_Fast_ITEMS(items), PySequence_Fast_GET_SIZE(items), depth);
                        }
                    }
                }
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

    PyObject* deep_to_py(PyObject* proxy, int depth)
    {
        const int handle = js_proxy_handle(proxy);
        if (handle == 0)
        {
            // not a JS object: nothing to convert
            return Py_NewRef(proxy);
        }
        Slot out[2];
        if (pyjs_js_to_py(handle, depth, ptr_to_num(out)) != 0)
        {
            raise_from_slot(out);
            return nullptr;
        }
        StreamReader reader;
        reader.next = num_to_ptr<Slot>(out[0].num);
        reader.text = num_to_ptr<char>(out[1].num);
        // The stream lives in memory JavaScript reuses for the next
        // conversion. That is safe: nothing below calls back into JavaScript
        // in a way that starts another conversion before this one is read.
        return read_value(reader);
    }

    PyObject* deep_to_js(PyObject* obj, int depth)
    {
        StreamWriter writer;
        writer.sequence_abc = hooks().sequence_abc;
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
