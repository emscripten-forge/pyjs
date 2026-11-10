# CDN (no install, no bundler)

The [npm package](npm.md) can be imported straight from
[jsDelivr](https://www.jsdelivr.com/) in a plain html page: no install, no
build step. The runtime, Python and its standard library are fetched from the
CDN too.

```html
<!doctype html>
<html>
<body>
<script type="module">
  const cdn = "https://cdn.jsdelivr.net/npm";
  const { initializePyjsRuntime } = await import(
    `${cdn}/@PYJS_NPM_PACKAGE@@@PYJS_NPM_VERSION@/dist/index.js`
  );

  // python + stdlib; conda packages (here numpy)
  // are installed at runtime
  const pyjs = await initializePyjsRuntime({
    extraPackages: ["numpy"],
  });

  pyjs.exec("import numpy as np; print(np.arange(10).sum())");
</script>
</body>
</html>
```

- Pin the version (`@@PYJS_NPM_VERSION@`): the JavaScript and the WebAssembly runtime must
  match, and pinned urls are cached by the browser.
- Import `dist/index.js` (wasm32) or `dist/wasm64.js` directly, not jsDelivr's
  `/+esm` variant: the runtime files are loaded relative to the module
  (`import.meta.url`), `/+esm` re-bundles it.
- It also works in module workers
  (`new Worker(url, { type: "module" })`) and in the devtools console
  (`await import(...)`).

The options of `initializePyjsRuntime` and the returned API are described in
[npm package](npm.md) and the [JavaScript API](JavaScript_API.md).
