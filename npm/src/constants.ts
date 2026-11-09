/** default channels for extra packages: emscripten-forge (6x) + conda-forge (noarch) */
export const DEFAULT_CHANNELS = [
  "https://repo.prefix.dev/emscripten-forge/6x",
  "conda-forge",
];

// replaced by npm/build.mjs (esbuild `define`)
declare const __PYJS_PACKAGE_NAME__: string;
declare const __PYJS_PACKAGE_VERSION__: string;

/** name / version of this npm package */
export const PACKAGE_NAME: string = __PYJS_PACKAGE_NAME__;
export const PACKAGE_VERSION: string = __PYJS_PACKAGE_VERSION__;

/**
 * fallback location of the runtime files (bundled apps): jsDelivr, exactly
 * this package version (the JS and the wasm must match)
 */
export const DEFAULT_CDN_URL = `https://cdn.jsdelivr.net/npm/${PACKAGE_NAME}@${PACKAGE_VERSION}/assets/`;
