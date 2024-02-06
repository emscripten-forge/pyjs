// 

//
// %% Javascript API tour

//
// %% Instantiate the pyjs wasm module

importScripts("./pyjs_runtime_browser.js");
let pyjs = await createModule({});

packages_json_url = origin + "/lite/xeus/kernels/xpython/empack_env_meta.json"
package_tarballs_root_url = origin + "/lite/xeus/kernel_packages/"
            
await pyjs.bootstrap_from_empack_packed_environment(
    packages_json_url,
    package_tarballs_root_url
)


// 
// %% Hello world

pyjs.eval("print('hello world')");

//
// %% Import a module

pyjs.exec(`
import numpy
print(numpy.random.rand(3))
`);