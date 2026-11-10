# Using pyjs

Three ways to bring pyjs into a web page:

- [npm package](npm.md): the recommended way, for apps with or without a
  bundler; Python packages are installed at runtime
- [CDN](cdn.md): one `import` in a plain html page, no install, no build step
- [C++ / static library](cpp.md) (advanced): deploying the raw runtime, or
  embedding pyjs into your own WebAssembly program

```{toctree}
:maxdepth: 2
:hidden:

npm
cdn
cpp
```
