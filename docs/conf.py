# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

project = "pyjs"
copyright = "2022, Thorsten Beier"
author = "Thorsten Beier"

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration



import os
import sys
import tempfile
import shutil
from pathlib import Path

this_dir = Path(os.path.abspath(os.path.dirname(__file__)))



use_lite = True
if os.environ.get('LITE') and os.environ.get('LITE') == '0':
    print('Not using lite')
    use_lite = False

 


extensions = [
    "myst_parser", 
    "sphinx_rtd_theme",
    'sphinx_gallery.gen_gallery',
]
if use_lite:
    extensions.append('jupyterlite_sphinx') 
            





templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]


# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = "sphinx_rtd_theme"
html_static_path = ["_static"]

source_suffix = [".rst", ".md"]


# -- Options for sphinx-gallery ----------------------------------------------
sphinx_gallery_conf = {
     'examples_dirs': '../examples',   # path to your example scripts
     'gallery_dirs': 'auto_examples',  # path to where to save gallery generated output,
     'example_extensions': {'.py', '.js', '.cpp'},
     'notebook_extensions': {'.py', '.js', '.cpp'},
}


