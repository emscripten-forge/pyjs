// %% [markdown]
// Welcome to the tour of the PYJS JavaScript API. This notebook demonstrates how to use the PYJS JavaScript API to run Python code in the browser.

// %% [code]

// the url differs depending on the deployment
importScripts("../../../../xeus/bin/pyjs_runtime_browser.js");
let locateFile = function(filename){
    if(filename.endsWith('pyjs_runtime_browser.wasm')){
        return `../../../../xeus/bin/pyjs_runtime_browser.wasm`;
    }
};
let pyjs = await createModule({locateFile:locateFile});
packages_json_url = "../../../../xeus/kernels/xpython/empack_env_meta.json"
package_tarballs_root_url = "../../../../xeus/kernel_packages/"          
await pyjs.bootstrap_from_empack_packed_environment(
    packages_json_url,
    package_tarballs_root_url
);


// %% [code]

pyjs.eval("print('hello world')");

// %% [code]
pyjs.exec(`
import numpy
print(numpy.random.rand(3))
`);