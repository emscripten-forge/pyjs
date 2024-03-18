# JavaScript API

## `pyjs`
The main module for the JavaScript API.
### `exec`
Execute a string of Python code.
### `exec_eval`
Execute a string of Python code and return the last expression.

Example:
```javascript
pyjs.exec(`
import numpy
print(numpy.random.rand(3))
`);
```

### `eval`
Evaluate a string with a Python expression.
### `async_exec_eval`
Schedule the execution of a string of Python code and return a promise.
The last expression is returned as the result of the promise.
### `eval_file`
Evaluate a file with Python code.
### `pyobject`
A Python object exported as a JavaScript class
#### `py_call`
Call the `__call__` method of a Python object.
#### `py_apply`
Call the `__call__` method of a Python object with an array of arguments.
#### `get`
Get an attribute of a Python object.

