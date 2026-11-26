"""Running code: JavaScript from Python (`run_js`), and Python source given as
text (`eval_code`, `eval_code_async`; these are what `runPython` /
`runPythonAsync` in JavaScript call). The names are pyodide's
(``pyodide.code``); `run_js` is also in PEP 818 (``jstypes.code``)."""

import ast
import importlib
import inspect
import linecache
import textwrap

import pyjs_core

__all__ = ["run_js", "eval_code", "eval_code_async"]

# The global `eval`, fetched once. Calling `eval` through a reference like
# this (not as `eval(...)` written in the code) is an "indirect eval": the
# code runs in the global scope, not inside some function of pyjs.
_eval = pyjs_core.global_this().eval


def run_js(code):
    """Evaluate JavaScript `code` in the global scope and return the value of
    its last expression.

    Example:
    ```python
    from pyjs import run_js

    assert run_js("1 + 2") == 3
    add = run_js("(a, b) => a + b")
    assert add(1, 2) == 3
    ```
    """
    if not isinstance(code, str):
        raise TypeError(f"run_js: the code must be a str, not {type(code).__name__}")
    return _eval(code)


def _pyimport(name):
    """What `pyimport(name)` in JavaScript returns: the module `name`; for a
    dotted name whose last part is no module, that attribute of the parent
    module (``"os.path.join"`` gives the function)."""
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError:
        parent, _, attribute = name.rpartition(".")
        if not parent:
            raise
        try:
            return getattr(importlib.import_module(parent), attribute)
        except AttributeError:
            pass
        # (the error of the import of the full name, outside the `except`
        # blocks so that it is not chained to the AttributeError)
    return importlib.import_module(name)


def _ends_with_semicolon(source):
    """Does the last line of code end with `;` (a comment after it does not
    count)? Like in IPython, that means "do not show the value"."""
    lines = source.rstrip().splitlines()
    return bool(lines) and lines[-1].split("#")[0].rstrip().endswith(";")


def _split_last_expression(source, return_mode, quiet_trailing_semicolon, filename, dedent):
    """Parse `source` and split it into (the statements to execute, the last
    expression to evaluate). Either part can be None.

    Why: `exec` runs statements but returns nothing, `eval` returns a value
    but only accepts one expression. To run a whole script AND get the value
    of its last line (like a notebook cell does) the script is cut in two:
    everything before the last line is executed, the last line is evaluated,
    provided it is an expression (`x + 1`) and not a statement (`x = 1`).

    `return_mode` says which value is returned: "last_expr" (as described),
    "last_expr_or_assign" (also the value of a last assignment `x = 1`), or
    "none". With `quiet_trailing_semicolon` a last line ending with `;`
    returns nothing. With `dedent` the indentation all lines share is
    removed first: code written as an indented multi-line string can be
    passed as it is.
    """
    if dedent:
        source = textwrap.dedent(source)
    # The source is no file: tell `linecache` its lines, so that tracebacks
    # can show them (as for code in files)
    linecache.cache[filename] = (len(source), None, source.splitlines(True), filename)
    body = ast.parse(source, filename).body
    if not body or return_mode == "none" or (quiet_trailing_semicolon and _ends_with_semicolon(source)):
        return (ast.Module(body=body, type_ignores=[]) if body else None), None
    last = body[-1]
    if isinstance(last, ast.Expr):
        statements = ast.Module(body=body[:-1], type_ignores=[]) if len(body) > 1 else None
        return statements, ast.Expression(body=last.value)
    if return_mode == "last_expr_or_assign":
        # `x = 1` / `x += 1` / `x: int = 1` with a plain name: run it, then
        # evaluate the name
        if isinstance(last, ast.Assign):
            # (`a = b = 2`: every target got the value, take the first)
            targets = last.targets[:1]
        elif isinstance(last, ast.AugAssign):
            targets = [last.target]
        elif isinstance(last, ast.AnnAssign):
            # (`x: int` without a value only declares: nothing to return)
            targets = [last.target] if last.value is not None else []
        else:
            targets = []
        if len(targets) == 1 and isinstance(targets[0], ast.Name):
            value = ast.Expression(body=ast.Name(id=targets[0].id, ctx=ast.Load()))
            ast.fix_missing_locations(value)
            return ast.Module(body=body, type_ignores=[]), value
    return ast.Module(body=body, type_ignores=[]), None


def _namespaces(globals, locals):
    """the namespaces to run code in: without `globals` a new, empty one
    (not the one of this module, which `exec` would take); without `locals`
    the same as `globals`, as at module level"""
    if globals is None:
        globals = {}
    if locals is None:
        locals = globals
    return globals, locals


def eval_code(
    source,
    globals=None,
    locals=None,
    *,
    return_mode="last_expr",
    quiet_trailing_semicolon=True,
    filename="<exec>",
    flags=0,
    dedent=True,
):
    """Run Python `source` and return the value of its last expression (None
    if it ends with a statement).

    Args:
        source: the code, any number of lines.
        globals / locals: the namespaces to run in, as for `exec` (default:
            a new namespace).
        return_mode: "last_expr" (the value of a last expression),
            "last_expr_or_assign" (also of a last assignment) or "none".
        quiet_trailing_semicolon: a last line ending with ``;`` returns None.
        filename: the file name in tracebacks.
        flags: compiler flags (`compile`).
        dedent: remove the indentation all lines share first.

    Example:
    ```python
    from pyjs import eval_code

    assert eval_code("x = 20\\nx + 1") == 21
    ```
    """
    globals, locals = _namespaces(globals, locals)
    statements, expression = _split_last_expression(source, return_mode, quiet_trailing_semicolon, filename, dedent)
    if statements is not None:
        exec(compile(statements, filename, "exec", flags=flags), globals, locals)
    if expression is not None:
        return eval(compile(expression, filename, "eval", flags=flags), globals, locals)
    return None


async def eval_code_async(
    source,
    globals=None,
    locals=None,
    *,
    return_mode="last_expr",
    quiet_trailing_semicolon=True,
    filename="<exec>",
    flags=0,
    dedent=True,
):
    """Like `eval_code`, for code that uses ``await`` at the top level.

    The code runs with module level semantics (like the asyncio REPL and
    IPython): assignments go to `globals`, each statement runs exactly once.
    """
    globals, locals = _namespaces(globals, locals)
    # lets the compiler accept `await` outside of a function
    flags |= ast.PyCF_ALLOW_TOP_LEVEL_AWAIT

    async def run(code):
        """run compiled code; if it contained an await, wait for it"""
        result = eval(code, globals, locals)
        # Code compiled with the flag above that really contains an `await`
        # is a coroutine: evaluating it only creates the coroutine, which
        # then has to be awaited to actually run.
        if code.co_flags & inspect.CO_COROUTINE:
            result = await result
        return result

    statements, expression = _split_last_expression(source, return_mode, quiet_trailing_semicolon, filename, dedent)
    if statements is not None:
        await run(compile(statements, filename, "exec", flags=flags))
    if expression is not None:
        return await run(compile(expression, filename, "eval", flags=flags))
    return None
