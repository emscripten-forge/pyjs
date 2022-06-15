#include "pyjs/macro_magic.hpp"
BEGIN_PYTHON_INIT(pyjs_error_handling) R"pycode(#"


# and object holding a javascript 
class JsHolder(object):
    def __init__(self, js_proxy):
        self._js_proxy = js_proxy

    def get_js_proxy(self):
        return self._js_proxy

class JsException(JsHolder, Exception):
    def __init__(self, err, message=None):            
        
        # default message
        if message is None:
            message = js.JSON.stringify(err, js.Object.getOwnPropertyNames(err))
        self.message = message


        # i
        Exception.__init__(self, self.message)
        JsHolder.__init__(self, js_proxy=err)

class JsGenericError(JsException):
    def __init__(self, err):
        super().__init__(err=err)
        self.value = err

class JsError(JsException):
    def __init__(self, err):
        super().__init__(err=err)

class JsInternalError(JsError):
    def __init__(self, err):
        super().__init__(err=err)

class JsRangeError(JsError):
    def __init__(self, err):
        super().__init__(err=err)

class JsReferenceError(JsError):
    def __init__(self, err):
        super().__init__(err=err)

class JsSyntaxError(JsError):
    def __init__(self, err):
        super().__init__(err=err)

class JsTypeError(JsError):
    def __init__(self, err):
        super().__init__(err=err)
            
class JsURIError(JsError):
    def __init__(self, err):
        super().__init__(err=err)
            

#)pycode"
END_PYTHON_INIT
