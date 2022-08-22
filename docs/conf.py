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

# https://stackoverflow.com/questions/2471804/using-sphinx-with-markdown-instead-of-restextensions = ['myst_parser']
extensions = ["myst_parser"]

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]


# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = "alabaster"
html_static_path = ["_static"]

# https://stackoverflow.com/questions/2471804/using-sphinx-with-markdown-instead-of-restextensions = ['myst_parser']
source_suffix = [".rst", ".md"]
