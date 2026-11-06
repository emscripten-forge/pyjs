# Sphinx configuration of the pyjs documentation.
#
# Build with `./build_local.sh wasm32 --docs`: this builds pyjs, builds
# xeus-python from source against it and passes that environment to
# jupyterlite-xeus (via PYJS_DOCS_KERNEL_PREFIX), so the interactive parts of
# the docs run the pyjs from this repository.

import os
import re
from pathlib import Path

import jupytext

HERE = Path(__file__).parent.resolve()
ROOT = HERE.parent

project = "pyjs"
author = "pyjs contributors"
copyright = "pyjs contributors"

extensions = [
    "myst_parser",
    "autoapi.extension",
    "sphinx.ext.napoleon",
    "jupyterlite_sphinx",
]

source_suffix = {
    ".rst": "restructuredtext",
    ".md": "markdown",
}
exclude_patterns = ["_build", "_generated", "Thumbs.db", ".DS_Store"]

myst_enable_extensions = ["colon_fence"]
# anchors for links like `development.md#tests`
myst_heading_anchors = 3
# pygments' cmake lexer stumbles over `\$` in the embedding example
suppress_warnings = ["misc.highlighting_failure"]

# -- html -----------------------------------------------------------------------
html_theme = "pydata_sphinx_theme"
html_title = "pyjs"
html_theme_options = {
    "github_url": "https://github.com/emscripten-forge/pyjs",
    "navigation_with_keys": False,
}

# -- python api -----------------------------------------------------------------
# sphinx-autoapi parses the sources instead of importing them:
# `pyjs_core` (C++) and `js` only exist inside the browser.
autoapi_type = "python"
autoapi_dirs = [str(ROOT / "module"), str(ROOT / "stubs")]
autoapi_file_patterns = ["*.pyi", "*.py"]
autoapi_root = "api/python"
autoapi_add_toctree_entry = False
autoapi_keep_files = False
autoapi_options = [
    "members",
    # e.g. the `pyjs` package itself has no docstring and would be hidden
    "undoc-members",
    "show-inheritance",
    "show-module-summary",
]

# The docstrings are written in markdown flavour (```python fences, `code`) with
# google style sections (handled by napoleon), autoapi renders them as rst.
_INLINE_CODE = re.compile(r"(?<![`:])`([^`\n]+)`(?!`)")


def _markdown_docstring_to_rst(app, what, name, obj, options, lines):
    out = []
    in_fence = False
    for line in lines:
        stripped = line.strip()
        indent = line[: len(line) - len(line.lstrip())]
        if stripped.startswith("```"):
            if not in_fence:
                language = stripped[3:].strip() or "text"
                out += [f"{indent}.. code-block:: {language}", ""]
                fence_indent = indent
            else:
                out.append("")
            in_fence = not in_fence
        elif in_fence:
            # keep the relative indentation, but indent into the directive
            out.append(f"{fence_indent}    {line[len(fence_indent):]}" if line.strip() else "")
        else:
            out.append(_INLINE_CODE.sub(r"``\1``", line))
    lines[:] = out


def setup(app):
    # before napoleon (priority 500), which then sees plain rst code blocks
    app.connect("autodoc-process-docstring", _markdown_docstring_to_rst, priority=400)


# -- jupyterlite ----------------------------------------------------------------
# the example scripts (jupytext "percent" format) become notebooks in jupyterlite:
# python examples run in xeus-python, javascript examples in the javascript
# kernel of jupyterlite-javascript-kernel (IFrame runtime)
NOTEBOOK_DIR = HERE / "_generated" / "notebooks"
KERNELSPECS = {
    ".py": {"name": "xpython", "display_name": "Python (XPython)", "language": "python"},
    ".js": {"name": "javascript", "display_name": "JavaScript (IFrame)", "language": "javascript"},
}


def _make_notebooks():
    NOTEBOOK_DIR.mkdir(parents=True, exist_ok=True)
    for suffix, kernelspec in KERNELSPECS.items():
        for script in sorted((ROOT / "examples").glob(f"*{suffix}")):
            notebook = jupytext.read(script)
            notebook.metadata["kernelspec"] = kernelspec
            jupytext.write(notebook, NOTEBOOK_DIR / f"{script.stem}.ipynb")


_make_notebooks()
# the files (not the directory), so they end up at the top level of jupyterlite
jupyterlite_contents = [str(p) for p in sorted(NOTEBOOK_DIR.glob("*.ipynb"))]
jupyterlite_bind_ipynb_suffix = False

# the kernel environment: xeus-python + pyjs built from this repository.
# (jupyterlite-xeus cannot detect the channels of an environment created from
# environment files, hence the default channel)
# Only files of conda packages (and the kernel) are packed from the prefix, so
# the pyjs python module (installed into the prefix by `make install`, not by a
# package) is mounted from the source tree. Its C++ part is linked into the
# xeus-python kernel (xpython.wasm).
_kernel_prefix = os.environ.get("PYJS_DOCS_KERNEL_PREFIX")
if _kernel_prefix:
    _py_ver = next(Path(_kernel_prefix, "include").glob("python3.*")).name  # e.g. python3.14
    jupyterlite_build_command_options = {
        "XeusAddon.prefix": _kernel_prefix,
        "XeusAddon.default_channels": "https://repo.prefix.dev/emscripten-forge/6x",
        "XeusAddon.mounts": f"{ROOT / 'module' / 'pyjs'}:/lib/{_py_ver}/site-packages/pyjs",
    }
else:
    print(
        "WARNING: PYJS_DOCS_KERNEL_PREFIX is not set, there is no python kernel "
        "for the jupyterlite in the docs and its build will fail "
        "(build the docs with `./build_local.sh wasm32 --docs`)"
    )

# the pyjs runtime (js / wasm) + a packed environment for the javascript kernel,
# prepared by build_local.sh --docs and deployed next to the jupyterlite:
# <html root>/pyjs-runtime/ (see examples/js_api_tour.js)
_extra_dir = os.environ.get("PYJS_DOCS_EXTRA_DIR")
if _extra_dir:
    html_extra_path = [_extra_dir]
