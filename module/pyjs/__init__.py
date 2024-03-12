import pyjs_core
from pyjs_core import *
from pyjs_core import JsValue

from . core import *
from . extend_js_val import *
from . error_handling import *
from . convert import *
from . convert_py_to_js import *
from . webloop import *
from . pyodide_polyfill import *

_in_browser_js = internal.module_property("_IS_NODE")
IN_BROWSER = not to_py(_in_browser_js)


js = sys.modules["pyjs_core.js"]
_module = sys.modules["pyjs_core._module"]

