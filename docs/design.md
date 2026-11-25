# Design

How Python and JavaScript reach each other in pyjs: the parts of the core,
and three diagrams of what happens on a call in each direction and on a deep
conversion. The source files named here explain the details in their
comments.

## The parts

Python runs inside WebAssembly (wasm). Wasm and JavaScript can only pass
plain numbers to each other, and every call across that border ("hop") costs
time. Everything below is built around doing each operation in ONE hop.

| part | what it is | where |
|---|---|---|
| **slot** | one value crossing the border: 16 bytes in wasm memory (a tag saying what kind of value, plus the value or its address). Arguments and results are slots; only their address is passed. | `src/slot.hpp`, `src/js/codec.ts` |
| **handle** | how Python refers to a JS object: an index into a table on the JS side (Python cannot hold a JS object, only a number). | `src/js/codec.ts` (`hNew` / `hGet` / `hFree`) |
| **JSProxy** | the Python object standing for a JS object (holds its handle). One Python type per set of abilities (callable, has a length, awaitable, ...). | `src/js_proxy.cpp`, `module/pyjs/_proxy_types.py` |
| **PyProxy** | the JS object standing for a Python object: an ES `Proxy` whose handler forwards property access, calls, ... into Python. | `src/js/pyproxy.ts` |
| **EM_JS functions** | the only way the C++ side calls JavaScript: one-liners calling `pyjsCore.xxx` (the JS half of the core). | `src/js_proxy.cpp`, `src/module.cpp`, `src/deep.cpp`, `src/js/index.ts` |
| **wasm exports** | the only way JavaScript calls Python: `pyjs_call`, `pyjs_op`, ... | `src/py_entry.cpp` |
| **hooks** | Python functions / classes of the `pyjs` package the C++ core calls back into (raise a JS error, await a promise, ...), handed over once by `pyjs_core.set_hooks`. | `src/slot.hpp` (`struct Hooks`), `module/pyjs/__init__.py` |
| **stream** | a whole structure (lists in dicts in ...) written as a run of slots, for the deep conversions `to_py` / `to_js`. | `src/deep.cpp`, `src/js/deep.ts` |

Errors never travel as exceptions across the border: each side returns a
return code and puts the thrown value / the exception into the result slot;
the receiving side raises / throws it in its own language.

## Python calls a JavaScript function

`f(1, "a")` in Python, where `f` is a JSProxy of a JS function:

```{mermaid}
sequenceDiagram
    participant Py as Python code
    participant C as C++<br/>js_proxy.cpp
    participant JS as JavaScript<br/>jsops.ts<br/>codec.ts
    participant F as JS<br/>function f

    Py->>C: f(1, "a")<br/>(the proxy's<br/>vectorcall)
    Note over C: to_slot each arg:<br/>1 → INT slot<br/>"a" → STR slot<br/>(utf8)<br/>Python object<br/>→ PY slot<br/>JSProxy<br/>→ its handle
    C->>JS: pyjs_js_call<br/>(f, slots)<br/>ONE hop
    Note over JS: decode each slot:<br/>numbers, strings<br/>→ JS values<br/>handles<br/>→ JS objects<br/>Python objects<br/>→ borrowed<br/>PyProxies
    JS->>F: Reflect.apply
    F-->>JS: value<br/>(or throws)
    Note over JS: encode result<br/>→ out slot<br/>(JS object<br/>→ new handle)<br/>destroy borrowed<br/>PyProxies
    JS-->>C: return code
    alt OK
        Note over C: from_slot(out):<br/>a Python value,<br/>or a JSProxy
        C-->>Py: result
    else ERROR
        Note over C: raise_from_slot<br/>→ hook<br/>raise_js_error<br/>→ JSException
        C-->>Py: raises
    end
```

## JavaScript calls a Python function

`proxy(1, "a")` in JavaScript, where `proxy` is a PyProxy of a Python
function:

```{mermaid}
sequenceDiagram
    participant JS as JavaScript<br/>code
    participant P as PyProxy<br/>pyproxy.ts
    participant E as wasm export<br/>py_entry.cpp
    participant F as Python<br/>function

    JS->>P: proxy(1, "a")<br/>(handler.apply)
    Note over P: encode the<br/>arguments into<br/>scratch slots<br/>(strings as utf8,<br/>too large: malloc)
    P->>E: pyjs_call<br/>(fn, slots)<br/>ONE hop
    Note over E: from_slot each arg:<br/>JS values<br/>→ Python objects<br/>JS objects<br/>→ JSProxies
    E->>F: PyObject_<br/>Vectorcall
    F-->>E: returns<br/>(or raises)
    alt returned
        Note over E: async def: start<br/>the coroutine as<br/>asyncio task<br/>to_slot(result)<br/>→ out slot
        E-->>P: OK
        Note over P: decode(out):<br/>a JS value, or an<br/>OWNED PyProxy
        P-->>JS: result
    else raised
        Note over E: write_error:<br/>3 slots<br/>(exception,<br/>traceback,<br/>type name)
        E-->>P: ERROR
        P-->>JS: throws PythonError
    end
```

With JSPI, entries that may suspend (`run_sync`) go through
`pyjs_call_promising`, wrapped in `WebAssembly.promising`: the call returns a
promise and the Python code can wait for JS promises in between (see
`src/js/jspi.ts`).

## Deep conversion (`to_py` / `to_js`)

Crossing the border, only simple values are converted automatically (None,
bools, numbers, strings); containers stay where they are and the other side
gets a proxy. `to_py` / `to_js` copy a whole structure instead, in one hop,
as a stream:

`to_py`, a JavaScript value becomes Python objects:

```{mermaid}
flowchart TD
    A["Python: pyjs.to_py(js_proxy)"] --> B["C++ deep_to_py (deep.cpp)"]
    B -- "ONE hop: handle, depth" --> C["JavaScript, deep.ts write():<br/>walks the JS value, writes the stream"]
    C -- "the stream in wasm memory" --> D["C++ read_value():<br/>reads the stream, builds lists / dicts / sets"]
    D --> E["Python: the new Python objects"]
```

`to_js`, a Python value becomes JavaScript objects:

```{mermaid}
flowchart TD
    A["Python: pyjs.to_js(obj)"] --> B["C++ write_value() (deep.cpp):<br/>walks the Python value, writes the stream"]
    B -- "ONE hop: the stream" --> C["JavaScript, deep.ts fromStream():<br/>builds Arrays / Objects / Maps / Sets / typed arrays"]
    C -- "the result slot" --> D["Python: a JSProxy of the new JS value"]
```

The stream for `[1, "a", {"x": 2}]`:

```
LIST 3 │ INT 1 │ STR "a" │ DICT 1 │ STR "x" │ INT 2
```

A container that appears a second time (shared, or containing itself) is
written as `REF n` ("the n-th container again"), so the copy has the same
sharing and cycles end. What is copied and what stays a proxy:

| Python → JavaScript (`to_js`) | JavaScript → Python (`to_py`) |
|---|---|
| list, tuple → Array | Array (and DOM lists) → list |
| dict → Object (`dict_converter`: e.g. Map) | Map, plain Object → dict |
| set → Set | Set → set |
| buffer (bytes, numpy, ...) → typed array (copy) | typed array, ArrayBuffer → memoryview (copy) |
| anything else → a PyProxy (`default_converter` may convert it) | anything else (functions, class instances) → a JSProxy |

`depth` limits how many levels of containers are copied; below that,
containers become proxies.

## The asyncio event loop

`module/pyjs/webloop.py` (adapted from pyodide) runs asyncio on the
browser's event loop: `call_soon` callbacks are posted on a private
`MessageChannel` (no 4 ms clamping of nested `setTimeout`), `call_later` uses
`setTimeout`. Every task step is therefore a call from JavaScript into
Python, like the one in the second diagram.
