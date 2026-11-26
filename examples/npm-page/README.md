# A web page with the pyjs npm package

The smallest page using the npm package: one `index.html`, no bundler, no
build step. It starts python in the browser and prints `hello world` into the
page.

```bash
npm install @derthorsten/pyjs
python -m http.server       # then open http://localhost:8000
```

The package brings everything: the pyjs runtime (wasm32 and wasm64), python
with its standard library and the `pyjs` module. More packages (numpy, ...)
come from emscripten-forge at runtime, see the `packages` option in the docs.

`check.py` opens the page in headless chromium and checks the output.

In the pyjs repository the page is tested with the package of the same
commit, built by `pixi run npm-package` (the CI runs it):

```bash
pixi run example-npm-page   # installs build_root/npm/tgz/*.tgz here, runs check.py
```
