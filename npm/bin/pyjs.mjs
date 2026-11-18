#!/usr/bin/env node
// pyjs npm package CLI
//
//   npx <package> copy-assets <dir> [--arch wasm32|wasm64]
//   npx <package> lock <spec>... [--arch wasm32|wasm64] [--channel <url>]... [-o <file>]
//
// copy-assets: copies the runtime + python environment (the package's
// `assets/`) to <dir>, e.g. the public / static folder of a bundled app; then
// `initializePyjsRuntime({ assetsUrl: "<url of dir>" })`.
// lock: solves the specs (at build time) against the python environment of
// this package and writes the pinned packages per architecture; then
// `initializePyjsRuntime({ urls: lock[arch] })` installs them without a solver.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const pkgRoot = path.resolve(here, "..");
const assets = path.join(pkgRoot, "assets");
const { name } = JSON.parse(fs.readFileSync(path.join(pkgRoot, "package.json"), "utf8"));

function usage(code = 1) {
  console.log(`usage: npx ${name} copy-assets <dir> [--arch wasm32|wasm64]
       npx ${name} lock <spec>... [--arch wasm32|wasm64] [--channel <url>]... [-o <file>]

copy-assets: copies the pyjs runtime + python environment (both architectures,
or only --arch) to <dir>, then pass its url as \`assetsUrl\`:

  initializePyjsRuntime({ assetsUrl: "/pyjs/" })   // <dir> served at /pyjs/

lock: solves the package specs against the python environment of this package
and writes the pinned packages (default: pyjs-lock.json), then

  initializePyjsRuntime({ urls: lock.wasm32 })      // no solver in the browser`);
  process.exit(code);
}

/** the values of `--<flag> x` / `--<flag>=x` (repeatable) and the other arguments */
function parse(args, flags) {
  const values = Object.fromEntries(flags.map((f) => [f, []]));
  const rest = [];
  for (let i = 0; i < args.length; i++) {
    const flag = flags.find((f) => args[i] === f || args[i].startsWith(`${f}=`));
    if (!flag) rest.push(args[i]);
    else if (args[i] === flag) values[flag].push(args[++i]);
    else values[flag].push(args[i].slice(flag.length + 1));
  }
  return { values, rest };
}

const available = fs.readdirSync(assets).filter((d) => fs.statSync(path.join(assets, d)).isDirectory());

function checkArchs(archs) {
  for (const arch of archs) {
    if (!available.includes(arch)) {
      console.error(`unknown --arch ${arch} (available: ${available.join(", ")})`);
      process.exit(1);
    }
  }
  return archs.length ? archs : available;
}

/** copy-assets <dir> [--arch ...] */
function copyAssets(args) {
  const { values, rest } = parse(args, ["--arch"]);
  if (rest.length !== 1) usage();
  const [dest] = rest;
  const archs = checkArchs(values["--arch"]);
  fs.mkdirSync(dest, { recursive: true });
  for (const arch of archs) {
    fs.rmSync(path.join(dest, arch), { recursive: true, force: true });
    fs.cpSync(path.join(assets, arch), path.join(dest, arch), { recursive: true });
  }
  console.log(`pyjs assets (${archs.join(", ")}) copied to ${path.resolve(dest)}`);
}

/** lock <spec>... [--arch ...] [--channel ...] [-o file] */
async function lock(args) {
  const { values, rest } = parse(args, ["--arch", "--channel", "-o"]);
  if (rest.length === 0) usage();
  const { createLock } = await import(pathToFileURL(path.join(here, "lock.mjs")).href);
  const result = await createLock({
    specs: rest,
    assetsDir: assets,
    archs: checkArchs(values["--arch"]),
    channels: values["--channel"].length ? values["--channel"] : undefined,
  });
  const out = values["-o"].at(-1) ?? "pyjs-lock.json";
  fs.writeFileSync(out, JSON.stringify(result, null, 2) + "\n");
  for (const [arch, pkgs] of Object.entries(result)) {
    console.log(`${arch}: ${pkgs.length} packages`);
  }
  console.log(`written: ${path.resolve(out)}`);
}

const [command, ...rest] = process.argv.slice(2);
if (command === "--help" || command === "-h") usage(0);
else if (command === "copy-assets") copyAssets(rest);
else if (command === "lock") await lock(rest);
else usage();
