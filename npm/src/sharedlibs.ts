/**
 * Preloading shared libraries (main thread): `dlopen` with the promise API of
 * emscripten, so the wasm is compiled asynchronously (a synchronous compile of
 * a large library at `import` time is not allowed in the main thread).
 * Libraries first (RTLD_GLOBAL: later libraries / extension modules resolve
 * their symbols), python extension modules last (RTLD_LOCAL, like CPython).
 */
const RTLD_NOW = 2;
const RTLD_GLOBAL = 256;

/** a python extension module (CPython loads them RTLD_LOCAL) */
function isExtensionModule(path: string): boolean {
  return /\.cpython-[^/]*\.so$/.test(path) || path.includes("/lib-dynload/");
}

/** dlopen `path` without blocking (emscripten_dlopen_promise) */
async function dlopen(Module: any, path: string, flags: number): Promise<void> {
  const stack = Module.stackSave();
  const pathUTF8 = Module.stringToUTF8OnStack(path);
  const pid = Module._emscripten_dlopen_promise(pathUTF8, flags);
  Module.stackRestore(stack);
  const promise = Module.getPromise(pid);
  Module.promiseMap.free(pid);
  try {
    await promise;
  } catch (e) {
    const err = Module._dlerror();
    const msg = err ? Module.UTF8ToString(err, 512).trim() : String(e);
    throw new Error(`pyjs: loading the shared library ${path}: ${msg}`);
  }
}

/** load `paths` (shared libraries of installed packages), one at a time */
export async function preloadSharedLibs(Module: any, paths: string[]): Promise<void> {
  const libs = paths.filter((p) => !isExtensionModule(p));
  const extensions = paths.filter(isExtensionModule);
  for (const path of libs) {
    await dlopen(Module, path, RTLD_NOW | RTLD_GLOBAL);
  }
  for (const path of extensions) {
    await dlopen(Module, path, RTLD_NOW);
  }
}
