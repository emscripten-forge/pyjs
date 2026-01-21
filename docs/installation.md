# Deploying pyjs

## Prerequisites

Before we start, lets introduce a few concepts and tools that are used in the pyjs workflow.

### Emscripten-forge

Similar to [conda-forge](https://conda-forge.org/), [emscripten-forge](https://github.com/emscripten-forge/recipes) provides packages which are compiled to WebAssembly using [Emscripten](https://emscripten.org/).

### Empack
[Empack](https://github.com/emscripten-forge/empack) is a tool to "pack" conda environments into a set of files that can be consumed by pyjs.

```bash
micromamba install empack -c conda-forge
```

## Installation Steps


### 1. Define a conda environment
Pyjs has a conda-like workflow. This means the first step
is to define a WebAssembly environment that includes `pyjs` and any other packages required for your project.

Create an *environment.yml* file with the following:

```yaml
name: my-pyjs-env
channels:
  - https://repo.prefix.dev/emscripten-forge-4x
  - https://repo.prefix.dev/conda-forge
dependencies:
  - pyjs
  - numpy
```

- The `name` of the environment can be chosen by the user.
- The `channels` section specifies the conda channels to use.
- The `https://repo.prefix.dev/emscripten-forge-4x` is mandatory to install the `pyjs` package.
- The `conda-forge` channel is used to install `noarch` packages.


Please note, all compiled packages need to be available in the [`emscripten-forge-4x`](https://prefix.dev/channels/emscripten-forge-4x) channel.

### 2. Create the environment
The environment can be created using `micromamba`:

```Bash
micromamba create -f environment.yml --platform emscripten-wasm32 --prefix /path/to/env
```

### 3. Populate the directory to be deployed

Create a deploy directory, */path/to/deploy/*, where we will
put all of the tools needed to be served to the user.

Copy the pyjs binary from the environment to the deploy directory.
This will move *pyjs_runtime_browser.js* and *pyjs_runtime_browser.wasm* to the deployment directory.

```Bash
cp /path/to/env/lib_js/pyjs/* /path/to/deploy/
```


### 4. Pack the environment

After the environment is defined, the next step is to pack the environment using `empack`.

```Bash
empack pack env --env-prefix /path/to/env --outdir /path/to/deploy
```
This will create a tarball for each package in the environment and a `empack_env_meta.json` file that describes the environment.


### 5. Add the HTML/JavaScript code

The last step is to create an html file that loads the pyjs runtime and the packed environment.

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
