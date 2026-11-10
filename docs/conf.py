# Sphinx configuration of the pyjs documentation.
#
# Build with `./build_local.sh docs`: builds the npm package of this repository
# (deployed next to the html, used by the playground), then sphinx.

import os
import re
from pathlib import Path

HERE = Path(__file__).parent.resolve()
ROOT = HERE.parent

project = "pyjs"
author = "pyjs contributors"
copyright = "pyjs contributors"

extensions = [
    "myst_parser",
    "autoapi.extension",
    "sphinx.ext.napoleon",
]

source_suffix = {
    ".rst": "restructuredtext",
    ".md": "markdown",
}
exclude_patterns = ["_build", "_extra", "Thumbs.db", ".DS_Store"]

myst_enable_extensions = ["colon_fence"]
# anchors for links like `development.md#tests`
myst_heading_anchors = 4
# pygments' cmake lexer stumbles over `\$` in the embedding example
suppress_warnings = ["misc.highlighting_failure"]

# -- html -----------------------------------------------------------------------
html_theme = "pydata_sphinx_theme"
html_title = "pyjs"
html_theme_options = {
    "github_url": "https://github.com/emscripten-forge/pyjs",
    "navigation_with_keys": False,
    # monokai only (like the playground): no light / dark switcher
    "navbar_end": ["navbar-icon-links"],
    "pygments_light_style": "monokai",
    "pygments_dark_style": "monokai",
}
html_context = {"default_mode": "dark"}
# _templates/navbar-nav.html: + the playground link in the header
templates_path = ["_templates"]
html_static_path = ["_static"]
html_css_files = ["monokai.css"]
# run buttons for the python / javascript snippets, executed by pyjs itself
# (the npm package deployed next to the html)
html_js_files = [("runnable.js", {"type": "module"})]

# -- python api -----------------------------------------------------------------
# sphinx-autoapi parses the sources instead of importing them:
# `pyjs_core` (C++) and `js` only exist inside the browser.
autoapi_type = "python"
autoapi_dirs = [str(ROOT / "module"), str(ROOT / "stubs")]
autoapi_file_patterns = ["*.pyi", "*.py"]
autoapi_root = "api/python"
autoapi_add_toctree_entry = False
autoapi_keep_files = False
# The Python API page (python_api.md) is written by hand with autoapi
# directives (`autoapifunction:: pyjs.run_sync`): one page with only the names
# meant for users, autoapi generates no pages itself.
autoapi_generate_api_docs = False
autoapi_options = ["members", "undoc-members", "imported-members", "show-inheritance"]

# The docstrings are written in markdown flavour (```python fences, `code`) with
# google style sections (handled by napoleon), autoapi renders them as rst.
_INLINE_CODE = re.compile(r"(?<![`:])`([^`\n]+)`(?!`)")


def _markdown_docstring_to_rst(app, what, name, obj, options, lines):
    """markdown flavoured docstrings (```fences, `code`) -> rst for autoapi"""
    out = []
    in_fence = False
    for line in lines:
        stripped = line.strip()
        indent = line[: len(line) - len(line.lstrip())]
        if stripped.startswith("```"):
            if not in_fence:
                language = stripped[3:].strip() or "text"
                # blank line before: directly after e.g. `Example:` it is no directive
                out += ["", f"{indent}.. code-block:: {language}", ""]
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
    """sphinx hooks: markdown docstrings, npm placeholders"""
    # before napoleon (priority 500), which then sees plain rst code blocks
    app.connect("autodoc-process-docstring", _markdown_docstring_to_rst, priority=400)
    app.connect("source-read", _fill_in_npm_package)


# -- npm package name / version in the pages ------------------------------------
# `@PYJS_NPM_PACKAGE@` / `@PYJS_NPM_VERSION@` in the markdown sources (e.g. the
# CDN urls) are replaced, so the docs always match the package of this version
NPM_PACKAGE = os.environ.get("NPM_PACKAGE_NAME", "@derthorsten/pyjs")
NPM_VERSION = re.search(
    r"project\(pyjs VERSION ([0-9.]+)", (ROOT / "CMakeLists.txt").read_text()
).group(1)


def _fill_in_npm_package(app, docname, source):
    """replace the npm placeholders in a page source"""
    source[0] = source[0].replace("@PYJS_NPM_PACKAGE@", NPM_PACKAGE).replace(
        "@PYJS_NPM_VERSION@", NPM_VERSION
    )


# -- deployed next to the html ----------------------------------------------------
# _extra/: the playground (<html root>/playground/); PYJS_DOCS_EXTRA_DIR (set by
# `build_local.sh docs`): the npm package built from this repository
# (<html root>/pyjs/), which the playground loads
html_extra_path = ["_extra"]
if os.environ.get("PYJS_DOCS_EXTRA_DIR"):
    html_extra_path.append(os.environ["PYJS_DOCS_EXTRA_DIR"])
