import contextlib
import json
import sys
import types
from typing import Any
import ast


def install_submodules():
    def _js_mod__getattr__(name: str) -> Any:
        ret = internal.global_property(name)
        if ret is None:
            raise AttributeError(f"has no attribute {name}")
        return ret

    js = sys.modules["pyjs.js"] = types.ModuleType("js")
    js.__getattr__ = _js_mod__getattr__

    def _module_mod__getattr__(name: str) -> Any:
        ret = internal.module_property(name)
        if internal.is_undefined_or_null(ret):
            raise AttributeError(f"has no attribute {name}")
        return ret

    _module = sys.modules["pyjs._module"] = types.ModuleType("_module")
    _module.__getattr__ = _module_mod__getattr__


install_submodules()
del install_submodules

# Expose "pyjs.js" module as "js" as well
js = sys.modules["js"] = sys.modules["pyjs.js"]
_module = sys.modules["pyjs._module"]


def new(cls_, *args):
    return _module._new(cls_, *args)


def async_import_javascript(path):
    return _module._async_import_javascript(path)


def type_str(x):
    return internal.type_str(x)


def create_callable(py_function):
    _js_py_object = js_py_object(py_function)
    return _js_py_object["py_call"].bind(_js_py_object), _js_py_object


@contextlib.contextmanager
def callable_context(py_function):
    cb, handle = create_callable(py_function)
    yield cb
    handle.delete()


class AsOnceCallableMixin(object):
    def __init__(self):
        self._once_callable = create_once_callable(self)

    def as_once_callable(self):
        return self._once_callable


def promise(py_resolve_reject):
    return js.Promise.new(create_once_callable(py_resolve_reject))


def create_once_callable(py_function):
    js_py_function = JsValue(py_function)
    once_callable = _module._create_once_callable(js_py_function)
    return once_callable


def _make_js_args(args):
    js_array_args = js_array()
    is_generated_proxy = js_array()
    for arg in args:
        js_arg, is_proxy = internal.implicit_py_to_js(arg)
        internal.val_call(js_array_args, "push", js_arg)
        internal.val_call(is_generated_proxy, "push", JsValue(is_proxy))
    return (js_array_args, is_generated_proxy)


def apply(js_function, args):
    js_array_args, is_generated_proxy = _make_js_args(args)
    ret, meta = internal.apply_try_catch(js_function, js_array_args, is_generated_proxy)
    return ret


def japply(js_function, args):
    sargs = json.dumps(args)
    ret, meta = internal.japply_try_catch(js_function, sargs)
    return ret


def gapply(js_function, args, jin=True, jout=True):
    if jin:
        args = json.dumps(args)
        is_generated_proxy = [False] * len(args)
    else:
        args, is_generated_proxy = _make_js_args(args)
    ret = internal.gapply_try_catch(js_function, args, is_generated_proxy, jin, jout)
    if jout:
        if ret == "":
            return None
        else:
            return json.loads(ret)
    else:
        return ret


def exec_eval(script, globals=None, locals=None):
    """Execute a script and return the value of the last expression"""
    stmts = list(ast.iter_child_nodes(ast.parse(script)))
    if not stmts:
        return None
    if isinstance(stmts[-1], ast.Expr):
        # the last one is an expression and we will try to return the results
        # so we first execute the previous statements
        if len(stmts) > 1:
            exec(
                compile(
                    ast.Module(body=stmts[:-1], type_ignores=[]),
                    filename="<ast>",
                    mode="exec",
                ),
                globals,
                locals,
            )
        # then we eval the last one
        return eval(
            compile(
                ast.Expression(body=stmts[-1].value), filename="<ast>", mode="eval"
            ),
            globals,
            locals,
        )
    else:
        # otherwise we just execute the entire code
        return exec(script, globals, locals)


import ast


async def async_exec_eval(stmts, globals=None, locals=None):
    parsed_stmts = ast.parse(stmts)
    if parsed_stmts.body:

        last_node = parsed_stmts.body[-1]
        if isinstance(last_node, ast.Expr):
            last_node = ast.Return(value=last_node.value)
            parsed_stmts.body.append(last_node)
            ast.fix_missing_locations(parsed_stmts)

    fn_name = "_pyjs_async_exec_f"
    fn = f"async def {fn_name}(): pass"
    parsed_fn = ast.parse(fn)
    for node in parsed_stmts.body:
        ast.increment_lineno(node)

    parsed_fn.body[0].body = parsed_stmts.body
    exec(compile(parsed_fn, filename="<ast>", mode="exec"), globals, locals)
    return await  eval(f'{fn_name}()', globals, locals)  # fmt: skip
