
function createLock() {
    let _lock = Promise.resolve();

    async function acquireLock() {
        const old_lock = _lock;
        let releaseLock = () => { };
        _lock = new Promise((resolve) => (releaseLock = resolve));
        await old_lock;
        return releaseLock;
    }
    return acquireLock;
}

 _lock = createLock();


 
 // * local
 // * global
 // * undefined // when we dont 
 function libraryType (path) {
    console.log("check lib type for", path);
    if (path.includes("cpython-3") && path.includes("-wasm32-emscripten.so")) {
        return "local";
    }
    return undefined;
 }

 function getFilenameFromPath(path) {
    const parts = path.split("/");
    return parts[parts.length - 1];
 }


async function loadDynlibsFromPackage(
    prefix,
    python_version,
    pkg_file_name,
    dynlibPaths,
) {



    // if(pkg_file_name == "zlib") {
    //     console.log("zlib is always loaded, skipping loading from package");
    //     return;
    // }
    if(prefix != "/")
    {
        throw `only root prefix / is supported for loading shared libraries from packages, got: ${prefix}`;
    }   

    console.log("LAPALUZA");

    // console.log("load shared objects from package:", pkg_file_name, dynlibPaths);
    for (let i = 0; i < dynlibPaths.length; i++) {
        let path = dynlibPaths[i];

        // // if the name contains "_tests" we skip loading the shared libraries
        // if (path.includes("_tests") || path.includes("_simd")) {
        //     console.log(`skipping loading shared libraries from package ${pkg_file_name} because it is a test package or simd package`);
        //     continue;
        // }

        const isSymlink = FS.isLink(FS.lstat(path));
        if (isSymlink) {
            console.log(`skipping symlinked shared library ${path} from package ${pkg_file_name}`);
            continue;
        }

        const releaseDynlibLock = await _lock();
        try {

            //#define RTLD_LAZY   1
            // #define RTLD_NOW    2
            // #define RTLD_NOLOAD 4
            // #define RTLD_NODELETE 4096
            // #define RTLD_GLOBAL 256
            // #define RTLD_LOCAL  0

            const libt = libraryType(path);
            let flag = 2; // RTLD_NOW
            // if(libt === "local"){
            //     console.log(`loading local shared library ${path} from package ${pkg_file_name}`);
            //     flag = 2 /* RTLD_NOW */ | 0 /* RTLD_LOCAL */;
            // }
            // else if(libt === "global"){
            //     console.log(`loading global shared library ${path} from package ${pkg_file_name}`);
            //     flag = 2 /* RTLD_NOW */ | 256 /* RTLD_GLOBAL */;
            // }
            // else{
            //     console.log(`loading shared library ${path} from package ${pkg_file_name} with default flags`);
            // }

            const stack = Module.stackSave();
            const pathUTF8 = Module.stringToUTF8OnStack(path);
            try {
                const pid = Module._emscripten_dlopen_promise(pathUTF8, flag);
                Module.stackRestore(stack);
                const promise = Module.getPromise(pid);
                Module.promiseMap.free(pid);
                // time it 
                const start = performance.now();

               
                await promise;




                const end = performance.now();



            } catch (e) {
                const dll_error_ptr = Module._dlerror();
                if (dll_error_ptr === 0) {
                    throw Error("unknown error loading shared library");
                }
                const error = Module.UTF8ToString(
                    dll_error_ptr,
                    512, // Use enough space for the error message
                );
                const error_msg =  error.trim();


                throw new Error(`error loading shared library ${path} from package ${pkg_file_name}: ${error_msg}`);
                
            }

            if(libt !== "local"){
                console.log('re-register shared library with filename without path');
                // get filename from path
                const filename = getFilenameFromPath(path);
                console.log(`registering shared library ${path} from package ${pkg_file_name} as ${filename} in global namespace`);
                // Module.LDSO.loadedLibsByName[filename] = Module.LDSO.loadedLibsByName[path];

            }
            console.log(`!!!!!!!!!shared library ${path} from package ${pkg_file_name} is ready`);
        } catch (e) {
            throw e;
        } finally { 
            console.log("release dynlib lock");
            releaseDynlibLock();
        }

    }
}

Module["_loadDynlibsFromPackage"] = loadDynlibsFromPackage;



