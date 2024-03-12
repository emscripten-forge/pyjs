# %% [markdown]
# A tour of the Python API
# ========================


# %% [code]
import pyjs



# %% [markdown]
# Accessing the the JavaScript global object
# ------------------------------------------
# The global object in javascript is accessible via `pyjs.js`.
# Since this example runs **not** in the main thread, but only
# in a worker thread, we can not acces the window object, but 
# only whats available in the workers global scope / globalThis.
# We can for instance print the page origin like this:
# 

# %% [code]
pyjs.js.location.origin  # equivalent to the javascript expression `location.origin` / `globalThis.location.origin`





# %% [markdown]
# Create JavaScript functions on the fly
# --------------------------------------
#
# To create a javascript fuction like the following
#
#   .. code-block:: JavaScript
#
#       my_function = function(a, b) {
#           return a + b;
#       }
# 
# we can do the following:

# %% [code]
# define the function
js_function = pyjs.js.Function("a", "b", "return a + b")

# %% [code]
# call the function
result = js_function(1, 2)
result