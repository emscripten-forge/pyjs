// Run the embedding program in node: node run.js <build dir>/embed.js
//
// createModule() resolves when the program is ready: the file packager's data
// (the standard library) is in the file system then. Python is started, prints
// "hello world", and the output is checked (exit code 1 if it is missing).
const path = require("path");

async function main() {
  const program = path.resolve(process.argv[2]);
  const createModule = require(program);
  const lines = [];
  const Module = await createModule({
    // embed.data (and embed.wasm) are next to embed.js, not in the cwd
    locateFile: (file) => path.join(path.dirname(program), file),
    // what the program (python's stdout) prints
    print: (line) => {
      console.log(line);
      lines.push(line);
    },
  });
  Module.startPython();
  Module.runPython('print("hello world")');
  if (!lines.includes("hello world")) {
    console.error("FAILED: python did not print 'hello world'");
    process.exit(1);
  }
  console.log("OK");
  // (python keeps the runtime alive for later calls: end explicitly)
  process.exit(0);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
