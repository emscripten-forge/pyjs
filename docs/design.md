# Design

## Main Idea
### pybind11
[Pybind11](https://github.com/pybind/pybind11) is a library that exposes C++ types in Python. It is a wrapper around the Python C API that allows for seamless integration of C++ and Python. 
To export a C++ class like the following to Python, you would use pybind11:

```C++
// foo.h
class Foo {
public:
    void say_hello() {
        std::cout << "Hello, World!" << std::endl;
    }
};
```

```C++
// main.cpp
#include <foo.h>
#include <pybind11/pybind11.h>

PYBIND11_MODULE(example, m) {
    py::class_<Foo>(m, "Foo")
        .def(py::init<>())
        .def("say_hello", &Foo::say_hello);
}
```
Not only can Python call C++ functions, but C++ can also call Python functions. In particular, one can interact
with Python objects. An object is represented by the `py::object` type on the C++ side. 

```C++
// main.cpp
py::object sys = py::module::import("sys");
py::object version = sys.attr("version");
std::string version_string = version.cast<std::string>();
std::cout << "Python version: " << version_string << std::endl;

```




### embind
There is a simmilar for emscripten called [embind](https://emscripten.org/docs/porting/connecting_cpp_and_javascript/embind.html). It allows you to expose C++ types to JavaScript.

```C++
// main.cpp
#include <foo.h>
#include <emscripten/bind.h>
using namespace emscripten;
// Binding code
EMSCRIPTEN_BINDINGS(my_class_example) {
  class_<Foo>("Foo")
    .constructor<>()
    .function("say_hello", &Foo::say_hello)
    ;
}
```
To access JavasScript from C++, you would use the `emscripten::val` type. This is the pendant to `py::object` in pybind11.

```C++
emscripten::val console = emscripten::val::global("console");
console.call<void>("log", "Hello, World!");
```

### pyjs
The main idea of pyjs is, to export emscripten `emscripten::val` objects to Python with pybind11 and to export pybind11 `py::object` objects to JavaScript with embind. 

That way, we get a seamless integration of Python and JavaScript with relatively little effort and high level C++
code.



## Error Handling

To catch JavaScript exceptions from Python, we wrap all JavaScript code in a try-catch block. If an exception is thrown, we catch it and raise a Python exception with the same message. 
The Python exceptions are directly translated to JavaScript exceptions.



## Memory Management
Any C++ class that is exported via embind needs to be deleted by hand with `delete` method. This is because the JavaScript garbage collector does not know about the C++ objects.
Therefore all `py::object` objects that are created from javascript objects need to be deleted by hand. This is done by calling the `delete` method on the `pyobject` object JavaScript side.


## Performance

Compared to pyodide, pyjs is slowwer when crossing the language barrier. Yet itm is fast enough for all practical purposes. 

## Packaging

Pyjs is exclusively via [emscripten-forge](https://github.com/emscripten-forge/recipes).

## Testing

To test pyjs without manually inspecting a web page, we use [pyjs-code-runner](https://github.com/emscripten-forge/pyjs-code-runner). This is a tool that runs a Python script in a headless browser and returns the output. 
