// Assemble the pyjs npm package (called by build_local.sh npm).
//
//   node build.mjs --out <package dir> --name <npm name> --version <version>
//                  --stage wasm32=<dir> [--stage wasm64=<dir>] [--no-minify]
//
// <dir> of a stage: pyjs_runtime_browser.{js,wasm} + the empack packed env
// (empack_env_meta.json + tarballs), see build_local.sh.
import { build } from "esbuild";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));

function parseArgs(argv) {
  const args = { stages: {}, minify: true };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--out") args.out = path.resolve(argv[++i]);
    else if (a === "--name") args.name = argv[++i];
    else if (a === "--version") args.version = argv[++i];
    else if (a === "--stage") {
      const [arch, dir] = argv[++i].split("=");
      args.stages[arch] = path.resolve(dir);
    } else if (a === "--no-minify") args.minify = false;
    else throw new Error(`unknown argument ${a}`);
  }
  for (const k of ["out", "name", "version"]) {
    if (!args[k]) throw new Error(`--${k} is required`);
  }
  if (!args.stages.wasm32) throw new Error("--stage wasm32=<dir> is required");
  return args;
}

const args = parseArgs(process.argv.slice(2));
const dist = path.join(args.out, "dist");
fs.rmSync(args.out, { recursive: true, force: true });
fs.mkdirSync(dist, { recursive: true });

// 1. javascript: one self-contained ESM per entry, the solver (mambajs +
//    rattler) is split into a chunk which is only loaded by `installPackages` /
//    `extraPackages`. All files in dist/ (chunks too): `import.meta.url`
//    based paths are the same in every file.
await build({
  absWorkingDir: here,
  entryPoints: { index: "src/index.ts", wasm32: "src/wasm32.ts", wasm64: "src/wasm64.ts" },
  outdir: dist,
  bundle: true,
  splitting: true,
  format: "esm",
  platform: "browser",
  target: "es2022",
  chunkNames: "[name]-[hash]",
  minify: args.minify,
  legalComments: "linked",
  // untarjs imports its wasm as a module; we locate it ourselves (assets/untarjs.wasm)
  loader: { ".wasm": "empty" },
  // node-only branches of the emscripten glue of untarjs (never run in a
  // browser) + our runtime loader (shipped unminified, see src/load-runtime.js)
  external: ["fs", "path", "crypto", "url", "module", "worker_threads", "./load-runtime.js"],
  define: {
    __PYJS_PACKAGE_NAME__: JSON.stringify(args.name),
    __PYJS_PACKAGE_VERSION__: JSON.stringify(args.version),
    // the emscripten glue of untarjs checks `typeof __filename`, which webpack
    // rewrites (-> "__filename is not defined" in the browser)
    __filename: "undefined",
    __dirname: "undefined",
    // node globals in node-only code paths: bundlers (parcel) see free
    // `process` / `Buffer` / `global` and try to bundle polyfills (which
    // fails without auto install, e.g. on CI). As property accesses they are
    // not node globals for them; the code behaves the same.
    process: "globalThis.process",
    Buffer: "globalThis.Buffer",
    global: "globalThis",
  },
  logLevel: "warning",
});
fs.copyFileSync(path.join(here, "src/load-runtime.js"), path.join(dist, "load-runtime.js"));
fs.mkdirSync(path.join(args.out, "assets"), { recursive: true });
fs.copyFileSync(
  path.join(here, "node_modules/@emscripten-forge/untarjs/lib/unpack.wasm"),
  path.join(args.out, "assets", "untarjs.wasm")
);
// `npx <package> copy-assets <dir>`
fs.mkdirSync(path.join(args.out, "bin"), { recursive: true });
fs.copyFileSync(path.join(here, "bin/pyjs.mjs"), path.join(args.out, "bin", "pyjs.mjs"));
fs.chmodSync(path.join(args.out, "bin", "pyjs.mjs"), 0o755);

// 2. type declarations (the public types do not import the bundled deps)
const typesDir = path.join(here, "build/types");
fs.rmSync(typesDir, { recursive: true, force: true });
execFileSync(process.execPath, [path.join(here, "node_modules/typescript/bin/tsc"), "-p", here], {
  stdio: "inherit",
});
for (const f of ["index", "wasm32", "wasm64", "types", "constants"]) {
  fs.copyFileSync(path.join(typesDir, `${f}.d.ts`), path.join(dist, `${f}.d.ts`));
}

// 3. runtime + packed environment per architecture
for (const [arch, stage] of Object.entries(args.stages)) {
  const target = path.join(args.out, "assets", arch);
  fs.cpSync(stage, target, { recursive: true });
  // the runtime is a classic MODULARIZE script; as ES module it only needs
  // an export (same file, no second link)
  const classic = path.join(target, "pyjs_runtime_browser.js");
  fs.writeFileSync(
    path.join(target, "pyjs_runtime_browser.mjs"),
    fs.readFileSync(classic, "utf8") + "\nexport default createModule;\n"
  );
  fs.rmSync(classic);
}

// 4. package.json, README, LICENSE
const python = (() => {
  const meta = JSON.parse(
    fs.readFileSync(path.join(args.stages.wasm32, "empack_env_meta.json"), "utf8")
  );
  return meta.packages.find((p) => p.name === "python")?.version;
})();
const exportsFor = (name) => ({
  types: `./dist/${name}.d.ts`,
  import: `./dist/${name}.js`,
  default: `./dist/${name}.js`,
});
const pkg = {
  name: args.name,
  version: args.version,
  description:
    "pyjs: python (CPython compiled to WebAssembly by emscripten-forge) with a python <-> JavaScript FFI, " +
    "including the standard library; extra conda packages are installed at runtime",
  license: "BSD-3-Clause",
  repository: { type: "git", url: "git+https://github.com/emscripten-forge/pyjs.git" },
  homepage: "https://emscripten-forge.github.io/pyjs",
  keywords: ["python", "wasm", "webassembly", "emscripten", "pyjs", "conda", "emscripten-forge"],
  type: "module",
  main: "./dist/index.js",
  module: "./dist/index.js",
  types: "./dist/index.d.ts",
  exports: {
    ".": exportsFor("index"),
    "./wasm32": exportsFor("wasm32"),
    "./wasm64": exportsFor("wasm64"),
    "./assets/*": "./assets/*",
    "./package.json": "./package.json",
  },
  bin: { pyjs: "bin/pyjs.mjs" },
  files: ["dist", "assets", "bin", "README.md", "LICENSE"],
  sideEffects: false,
  pyjs: { python, architectures: Object.keys(args.stages) },
};
fs.writeFileSync(path.join(args.out, "package.json"), JSON.stringify(pkg, null, 2) + "\n");
fs.writeFileSync(
  path.join(args.out, "README.md"),
  fs.readFileSync(path.join(here, "README.md"), "utf8").replaceAll("@PACKAGE_NAME@", args.name).replaceAll("@PACKAGE_VERSION@", args.version)
);
fs.copyFileSync(path.join(here, "../LICENSE"), path.join(args.out, "LICENSE"));
console.log(`npm package ${args.name}@${args.version} (python ${python}): ${args.out}`);
