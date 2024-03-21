# Welcome to `pyjs`

Pyjs is a python - javascript FFI for webassembly. 
It allows you to write python code and run it in the browser. 


## Quickstart

Access Javascript from Python:

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

Access Python from Javascript:

```JavaScript
// hello world
pyjs.eval("print('Hello, World!')")

// eval a python expression and get the result
const py_list = pyjs.eval("[i for i in range(10)]")

/// access 
console.log(py_list.get(0)) // same as py_list[0] on the python side
```
