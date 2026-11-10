#!/usr/bin/env node
// pyjs npm package CLI
//
//   npx <package> copy-assets <dir> [--arch wasm32|wasm64]
//
// copies the runtime + python environment (the package's `assets/`) to <dir>,
// e.g. the public / static folder of a bundled app; then
// `initializePyjsRuntime({ assetsUrl: "<url of dir>" })`.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const pkgRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const assets = path.join(pkgRoot, "assets");
const { name } = JSON.parse(fs.readFileSync(path.join(pkgRoot, "package.json"), "utf8"));

function usage(code = 1) {
  console.log(`usage: npx ${name} copy-assets <dir> [--arch wasm32|wasm64]

copies the pyjs runtime + python environment (both architectures, or only
--arch) to <dir>, then pass its url as \`assetsUrl\`:

  initializePyjsRuntime({ assetsUrl: "/pyjs/" })   // <dir> served at /pyjs/`);
  process.exit(code);
}

const [command, ...rest] = process.argv.slice(2);
if (command === "--help" || command === "-h") usage(0);
if (command !== "copy-assets") usage();

let dest;
const archs = [];
for (let i = 0; i < rest.length; i++) {
  if (rest[i] === "--arch") archs.push(rest[++i]);
  else if (rest[i].startsWith("--arch=")) archs.push(rest[i].slice("--arch=".length));
  else if (!dest) dest = rest[i];
  else usage();
}
if (!dest) usage();
const available = fs.readdirSync(assets).filter((d) => fs.statSync(path.join(assets, d)).isDirectory());
for (const arch of archs) {
  if (!available.includes(arch)) {
    console.error(`unknown --arch ${arch} (available: ${available.join(", ")})`);
    process.exit(1);
  }
}

fs.mkdirSync(dest, { recursive: true });
fs.copyFileSync(path.join(assets, "untarjs.wasm"), path.join(dest, "untarjs.wasm"));
for (const arch of archs.length ? archs : available) {
  fs.rmSync(path.join(dest, arch), { recursive: true, force: true });
  fs.cpSync(path.join(assets, arch), path.join(dest, arch), { recursive: true });
}
console.log(`pyjs assets (${(archs.length ? archs : available).join(", ")}) copied to ${path.resolve(dest)}`);
