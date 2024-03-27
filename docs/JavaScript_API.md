# JavaScript API

## `pyjs`
The main module for the JavaScript API.
### `exec`
Execute a string of Python code.

Example:
```javascript
pyjs.exec(`
import numpy
print(numpy.random.rand(3))
`);
```

### `exec_eval`
Execute a string of Python code and return the last expression.

Example:
```javascript
const arr = pyjs.exec_eval(`
import numpy
numpy.random.rand(3)
`);
// use the array
console.log(arr);
// delete the array
arr.delete();
```

### `eval`
Evaluate a string with a Python expression.

Example:
```javascript
const result = pyjs.eval("sum([i for i in range(100)])")
console.log(result); // 4950
```

### `async_exec_eval`
Schedule the execution of a string of Python code and return a promise.
The last expression is returned as the result of the promise.

Example:
```javascript
const py_code = `
import asyncio
await asyncio.sleep(2)
sum([i for i in range(100)])
`
result = await pyjs.async_exec_eval(py_code)
console.log(result); // 4950
```

### `eval_file`
Evaluate a file from the virtual file system.

Example:
```javascript
const file_content = `
import numpy

def fobar():
    return "fubar"

def foo():
  return "foo"
    
if __name__ == "__main__":
    print(fobar())
`
pyjs.FS.writeFile("/hello_world.py", file_content);

// evaluate the file
// print "fubar"
pyjs.eval_file("/hello_world.py")

// use content from files scope
// prints foo
pyjs.eval("foo()") ;
```

### `pyobject`
A Python object exported as a JavaScript class.
In Python, allmost everything is an object. This class holds the Python object 
compiled to JavaScript.




#### `py_call`
Call the `__call__` method of a Python object.

Example:
```javascript
const py_code = `
class Foobar:
    def __init__(self, foo):
        self.foo = foo
    def bar(self):
      return f"I am {self.foo}"

    def __call__(self, foobar):
      print(f"called Foobar.__call__ with foobar {foobar}")
      
# last statement is returned 
Foobar
`

// py_foobar_cls is a pyobject on
// the JavaScript side and the class Foobar
// on the Python side
var py_foobar_cls = pyjs.exec_eval(py_code)

// all function call-like statements (ie Foobar(2) need to be done via py_call)
var instance  = py_foobar_cls.py_call(2)
// prints 2
console.log(instance.foo)

// prints "I am 2"
console.log(instance.bar.py_call())

// prints called Foobar.__call__ with foobar 42
instance.py_call(42)
```

#### `py_apply`
Call the `__call__` method of a Python object with an array of arguments.

#### `get`
call the bracket operator `[]` of a Python object.

Example:
```javascript
const arr = pyjs.exec_eval("import numpy;numpy.eye(2)");
console.log(arr.get(0,0)) // prints 1
console.log(arr.get(0,1)) // prints 0
console.log(arr.get(1,0)) // prints 0
console.log(arr.get(1,1)) // prints 1
```