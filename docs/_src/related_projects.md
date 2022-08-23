# Related Projects


## Emscripten-forge

With emscripten forge we provide a mamba/conda channel for `emscripten-32` wasm packages.
The build instructions, also called "recipes", are stored at the
[github.com/emscripten-forge/recipes](https://github.com/emscripten-forge/recipes) repository.
To create new packages for `emscripten-32`, one has to add a new recipe to that repository.


## Empack
Empack is responsible for packaging files as `*.js/*.data` st. they can be used to populating Emscripten’s [virtual file system](https://emscripten.org/docs/porting/files/file_systems_overview.html#file-system-overview) when the page is loaded.
Empack is a convenient wrapper around emscripten filepackager with functionality centered around packaging mamba/conda environments.

[emscripten-forge/empack](https://github.com/emscripten-forge/empack)
