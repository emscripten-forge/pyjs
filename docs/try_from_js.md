

# Try pyjs from JavaScript 

<iframe
  src="../lite/repl/index.html?kernel=xjavascript&theme=JLDracula&code=importScripts(`../../../../xeus/bin/pyjs_runtime_browser.js`);%0A
let locateFile = function(filename){%0A
    if(filename.endsWith('pyjs_runtime_browser.wasm')){%0A
        return `../../../../xeus/bin/pyjs_runtime_browser.wasm`;%0A
    }%0A
};%0A
let pyjs = await createModule({locateFile:locateFile});%0A
const packages_json_url = `../../../../xeus/kernels/xpython/empack_env_meta.json`;%0A
const package_tarballs_root_url = `../../../../xeus/kernel_packages/`;%0A
await pyjs.bootstrap_from_empack_packed_environment(packages_json_url,package_tarballs_root_url);%0A
%0A%0A%0A%0A%0A%0A%0A%0A%0A%0A%0A%0A%0A%0A%0A%0A%0A%0A%0A%0A%0A%0A%0A%0A%0A%0A%0A%0A%0A%0A%0A%0A
pyjs.exec(`import numpy;print(numpy.random.rand(3))`);
"
  width="100%"
  height="300px"
></iframe>

