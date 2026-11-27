# Python API

Using JavaScript from Python, with the `pyjs` module: everything below is
available as `pyjs.<name>`. The API follows
[PEP 818](https://peps.python.org/pep-0818/) and pyodide: the same names are
also importable as `js`, `jstypes.ffi`, `pyodide.ffi` and `pyodide.code`, so
code written for pyodide runs unchanged.

```python
import pyjs

pyjs.js.console.log("hello from python")
add = pyjs.js.Function("a", "b", "return a + b")
add(1, 2)  # 3
```

## Accessing JavaScript

Numbers, strings, booleans, `undefined` (`None`) and `null` (`jsnull`) are
converted when they cross over; every other JavaScript value is a `JSProxy` in
Python: attributes, items, calls, iteration and `await` go to JavaScript.

```{eval-rst}
.. autoapidata:: pyjs.js

.. autoapiclass:: pyjs_core.JSProxy
   :members:

.. autoapidata:: pyjs.jsnull

.. autoapiclass:: pyjs.JSNull

.. autoapiclass:: pyjs.JSBigInt
```

### What a proxy can do

A proxy gets the methods of the classes below that fit its JavaScript object
(`isinstance(proxy, JSArray)` works too).

```{eval-rst}
.. autoapiclass:: pyjs.JSCallable
   :members:

.. autoapiclass:: pyjs.JSArray
   :members:

.. autoapiclass:: pyjs.JSTypedArray
   :members:

.. autoapiclass:: pyjs.JSBuffer
   :members:

.. autoapiclass:: pyjs.JSMap
   :members:

.. autoapiclass:: pyjs.JSMutableMap
   :members:

.. autoapiclass:: pyjs.JSPromise

.. autoapiclass:: pyjs.JSIterable

.. autoapiclass:: pyjs.JSIterator
   :members:

.. autoapiclass:: pyjs.JSGenerator
   :members:

.. autoapiclass:: pyjs.JSAsyncIterable

.. autoapiclass:: pyjs.JSAsyncIterator

.. autoapiclass:: pyjs.JSAsyncGenerator
   :members:

.. autoapiclass:: pyjs.JSDoubleProxy
   :members:
```

## Python objects for JavaScript

A Python object passed to a JavaScript function is only usable during that
call. For JavaScript to keep it (an event handler, a callback stored for
later), make a proxy that lasts.

```{eval-rst}
.. autoapifunction:: pyjs.create_proxy

.. autoapifunction:: pyjs.create_once_callable

.. autoapifunction:: pyjs.destroy_proxies
```

## Converting values

```{eval-rst}
.. autoapifunction:: pyjs.to_js

.. autoapifunction:: pyjs.to_py

.. autoapifunction:: pyjs.buffer_to_js_typed_array

.. autoapiclass:: pyjs.ConversionError
```

## Running JavaScript and Python code

```{eval-rst}
.. autoapifunction:: pyjs.run_js

.. autoapifunction:: pyjs.eval_code

.. autoapifunction:: pyjs.eval_code_async
```

## Waiting for promises: `run_sync` (JSPI)

`await` works on JavaScript promises in `async` code. Plain (synchronous)
Python code can block on a promise with `run_sync`, where the browser supports
JSPI (JavaScript Promise Integration). Any number of Python call stacks can
wait in `run_sync` at the same time; they continue in whatever order their
promises settle.

```{eval-rst}
.. autoapifunction:: pyjs.run_sync

.. autoapifunction:: pyjs.can_run_sync

.. autoapifunction:: pyjs.jspi_enabled
```

## The asyncio event loop

```{eval-rst}
.. autoapiclass:: pyjs.WebLoop

.. autoapifunction:: pyjs.set_main_loop_callback

.. autoapifunction:: pyjs.cancel_main_loop
```

## Graphics: WebGL2 / OpenGL ES 3, SDL2

The runtime contains emscripten's WebGL2 (OpenGL ES 3) and SDL2 support, so
extension modules using GLES 3 or SDL2 (e.g. via `ctypes` or C++) work in the
browser. They render into the canvas set with `set_canvas`.

```{eval-rst}
.. autoapifunction:: pyjs.set_canvas

.. autoapifunction:: pyjs.request_animation_frame_loop

.. autoapiclass:: pyjs.AnimationFrameLoop
   :members:
```

## JavaScript errors

A value thrown by JavaScript (or a rejected promise that is awaited) is raised
as `JSException`. Its `name` is the JavaScript error class (`"TypeError"`,
`"AbortError"`, ...), `message` its message.

```{eval-rst}
.. autoapiclass:: pyjs.JSException
```
