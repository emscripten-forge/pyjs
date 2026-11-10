// Loads the emscripten runtime of pyjs (an ES module served next to the
// python environment) at runtime. This file is shipped as is (not minified):
// the comments tell the bundlers of our users not to bundle this import.
export default function loadRuntime(url) {
  return import(/* webpackIgnore: true */ /* @vite-ignore */ url);
}
