# Python API

Using JavaScript from Python, with the `pyjs` module: everything below is
available as `pyjs.<name>`.

```python
import pyjs

pyjs.js.console.log("hello from python")
add = pyjs.js.Function("a", "b", "return a + b")
add(1, 2)  # 3
```

## Accessing JavaScript

Every JavaScript value is a `pyjs.JsValue` in Python (defined in the C++ core
`pyjs_core`): attributes, items and calls go to JavaScript.

```{eval-rst}
.. autoapidata:: pyjs.js

.. autoapiclass:: pyjs_core.JsValue
   :members:

.. autoapifunction:: pyjs.new

.. autoapifunction:: pyjs.async_import_javascript
```

## Converting values

```{eval-rst}
.. autoapifunction:: pyjs.to_js

.. autoapifunction:: pyjs.to_py

.. autoapifunction:: pyjs.register_converter

.. autoapifunction:: pyjs.buffer_to_js_typed_array
```

## Python callables for JavaScript

```{eval-rst}
.. autoapifunction:: pyjs.create_callable

.. autoapifunction:: pyjs.callable_context

.. autoapifunction:: pyjs.create_once_callable
```

## Promises

```{eval-rst}
.. autoapifunction:: pyjs.promise

.. autoapifunction:: pyjs.run_sync

.. autoapifunction:: pyjs.can_run_sync

.. autoapifunction:: pyjs.jspi_enabled
```

## Running Python code

```{eval-rst}
.. autoapifunction:: pyjs.exec_eval

.. autoapifunction:: pyjs.async_exec_eval
```

## The asyncio event loop

```{eval-rst}
.. autoapiclass:: pyjs.WebLoop

.. autoapifunction:: pyjs.set_main_loop_callback

.. autoapifunction:: pyjs.cancel_main_loop
```

## JavaScript errors

JavaScript errors (thrown or rejected promises) are raised as `JsException`
subclasses, by the class of the JavaScript error.

```{eval-rst}
.. autoapiclass:: pyjs.JsException
   :members:

.. autoapiclass:: pyjs.JsError
.. autoapiclass:: pyjs.JsTypeError
.. autoapiclass:: pyjs.JsRangeError
.. autoapiclass:: pyjs.JsReferenceError
.. autoapiclass:: pyjs.JsSyntaxError
.. autoapiclass:: pyjs.JsURIError
.. autoapiclass:: pyjs.JsInternalError
.. autoapiclass:: pyjs.JsGenericError
```
