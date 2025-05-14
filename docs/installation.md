# Deploying pyjs

## Prerequisites:

Before we start, lets introduce a few concepts and tools that are used in the pyjs workflow.
### Conda-forge Emscripten-Forge

[Emscripten-forge](https://github.com/emscripten-forge/recipes) is similar to [conda-forge](https://conda-forge.org/) and provides packages compiled to webassembly using emscripten.

### Empack
https://github.com/emscripten-forge/empack is a tool to "pack" conda environments into a set of files that can be consumed by pyjs.


## Installation Steps

So we assume there is a directory called `/path/to/deploy` where we will
put all tools which  need to be served to the user.

### Define a conda environment
Pyjs has a conda-like workflow. This means the first step 
is to create a environment with the `pyjs` package installed
and all packages required for the project.

```yaml
name: my-pyjs-env 
channels:
  - https://repo.mamba.pm/emscripten-forge 
  - conda-forge
dependencies:
  - pyjs
  - numpy
```

The name of the environment can be choosen by the user.
The `channels` section specifies the conda channels to use.
The `https://repo.mamba.pm/emscripten-forge` is mandatory to install the `pyjs` package.
The `conda-forge` channel is used to install `noarch`.
All compiled packages need to be available in the `emscripten-forge` channel.

### Create the environment
Assuming the yaml file above is called `environment.yml` and is in the current directory, the  environment can be created using `micromamba`:

```Bash
micromamba create -f environment.yml --platform emscripten-wasm32 --prefix /path/to/env
```

### Copy pyjs
Copy the pyjs binary from the environment to the deploy directory.
This should move pyjs_runtime_browser.js and pyjs_runtime_browser.wasm to the deployment directory.

```Bash
cp /path/to/env/lib_js/pyjs/* /path/to/deploy
```



### Pack the environment

After the environment is defined, the next step is to pack the environment using `empack`.

```Bash
empack pack env --env-prefix /path/to/env --outdir /path/to/deploy
```
This will create a tarball for each package in the environment and a `empack_env_meta.json` file that describes the environment.


### The html/JavaScript code

The last step is to create a html file that loads the pyjs runtime and the packed environment.

```html
<!DOCTYPE html>
<html>
  <head>
    <title>Pyjs Example</title>
    <script src="pyjs_runtime_browser.js"></script> 
    <script>
      async function runPyjs() {

        let locateFile = function(filename){
            if(filename.endsWith('pyjs_runtime_browser.wasm')){
                return `./pyjs_runtime_browser.wasm`; // location of the wasm 
                                                    // file on the server relative 
                                                    // to the pyjs_runtime_browser.js file
            }
        };
        let pyjs = await createModule({locateFile});
        await pyjs.bootstrap_from_empack_packed_environment(
            "./empack_env_meta.json", // location of the environment 
                                      // meta file on the server
            "."                       // location of the packed 
                                      // environment on the server
        );

        // now we can use pyjs
        pyjs.eval("print('hello world')");
      }
      runPyjs();

    </script>
  </head>
  <body>
    <h1>Pyjs Example</h1>
  </body>
```
