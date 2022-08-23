
# Xeus Python

The [xeus-python](https://github.com/jupyter-xeus/xeus-python) [jupyterlite-kernel](https://github.com/jupyterlite/xeus-python-kernel)
uses `pyjs`. In particular the event loop for `async` programming relies on `pyjs`.

With the following code one can create a xeus-python instance with a custom set of packages available:

```code
pip install jupyterlite
pip install jupyterlite-xeus-python
jupyter lite build --XeusPythonEnv.packages=numpy,matplotlib,ipyleaflet
jupyter lite serve
```

A nice example for such a xeus-python jupyterlite instance is the [ipycanvas](https://ipycanvas.readthedocs.io/en/latest/) demo:

<iframe width="100%" height="860" src="https://ipycanvas.readthedocs.io/en/latest/lite/lab/">
    <iframe>
