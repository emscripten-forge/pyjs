# %% [markdown]
# # A tour of the Python API


# %% [code]
import pyjs

# %% [markdown]
# # Accessing the the JavaScript global object
#
# The global object in javascript is accessible via `pyjs.js`.
# Since this example runs **not** in the main thread, but only
# in a worker thread, we can not acces the window object, but 
# only whats available in the workers global scope / globalThis.
# We can for instance print the page origin like this:
# 

# %% [code]
pyjs.js.location.origin  # equivalent to the javascript expression `location.origin` / `globalThis.location.origin`

# %% [markdown]
# # Create JavaScript functions on the fly

# %% [code]
# define the function
js_function = pyjs.js.Function("a", "b", "return a + b")

# %% [code]
# call the function
result = js_function(1, 2)
result

# %% [markdown]
# # Type conversion
#
# Pyjs allows to convert between python and javascript types.
#
# ## Explicit conversion

# %% [code]
# convert a python list to a javascript array
js_list = pyjs.js.eval("[1,2,3]")
# pylist is a vanilla python list
py_list = pyjs.to_py(js_list)
py_list

# %% [code]
# convert a nested javascript object to a python dict
js_nested_object = pyjs.js.Function("return{ foo:42,bar:[1,{a:1,b:2}]};")()
py_dict = pyjs.to_py(js_nested_object)
py_dict

# %% [markdown]
# ### Custom converters
#
# Pyjs allows to register custom converters for specific javascript classes.

# %% [code]
# Define JavaScript Rectangle class
# and create an instance of it
rectangle = pyjs.js.Function("""
    class Rectangle {
    constructor(height, width) {
        this.height = height;
        this.width = width;
    }
    }
    return new Rectangle(10,20)
""")()

# A Python Rectangle class
class Rectangle(object):
    def __init__(self, height, width):
        self.height = height
        self.width = width

# the custom converter
def rectangle_converter(js_val, depth, cache, converter_options):
    return Rectangle(js_val.height, js_val.width)

# Register the custom converter
pyjs.register_converter("Rectangle", rectangle_converter)

# Convert the JavaScript Rectangle to a Python Rectangle
r = pyjs.to_py(rectangle)
assert isinstance(r, Rectangle)
assert r.height == 10
assert r.width == 20

# %% [markdown]
# ## Implicit conversion
# ## Implicit conversion
# Fundamental types are automatically converted between Javascript and Python.
# This includes numbers, strings, booleans and undefined and null. 

# %% [code]
# this will convert the javascript string to a python string 
origin = pyjs.js.location.origin
assert isinstance(origin, str)

# or results from a javascript function
js_function = pyjs.js.Function("a", "b", "return a + b")
result = js_function("hello", "world")
assert isinstance(js_function("hello", "world"), str)
assert isinstance(js_function(1, 2), int)
assert isinstance(js_function(1.5, 2.0), float)
assert isinstance(js_function(1.5, 2.5), int) # (!)