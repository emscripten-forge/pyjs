# Welcome to `pyjs`

Pyjs is a Python - JavaScript FFI for WebAssembly.
It allows you to write python code and run it in the browser.


## Quick Start

Access JavaScript from Python:

```python
import pyjs

# hello world
pyjs.js.console.log("Hello, World!")

# create a JavaScript function to add two numbers
js_function = pyjs.js.Function("a", "b", """
    console.log("Adding", a, "and", b)
    return a + b
""")

# call the function
result = js_function(1, 2)
```

Access Python from JavaScript:

```JavaScript
// hello world
pyjs.eval("print('Hello, World!')")

// eval a python expression and get the result
const py_list = pyjs.eval("[i for i in range(10)]")

/// access
console.log(py_list.get(0)) // same as py_list[0] on the python side
```

## Try it out!

To try it out, you can use  [jupyterlite](../lite),
the [JavaScript REPL](try_from_js) or the [Python REPL](try_from_py).