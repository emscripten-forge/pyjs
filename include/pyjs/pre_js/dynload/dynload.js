
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
 // * undefined // when we dont  know (ie almost always ^^)
 function libraryType (path) {
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

    if(prefix != "/")
    {
        throw `only root prefix / is supported for loading shared libraries from packages, got: ${prefix}`;
    }   

    // console.log("load shared objects from package:", pkg_file_name, dynlibPaths);
    for (let i = 0; i < dynlibPaths.length; i++) {
        let path = dynlibPaths[i];

        const isSymlink = FS.isLink(FS.lstat(path));
        if (isSymlink) {
            continue;
        }

        const releaseDynlibLock = await _lock();
        try {

            // RTLD_LAZY            1
            // RTLD_NOW             2
            // RTLD_NOLOAD          4
            // RTLD_NODELETE     4096
            // RTLD_GLOBAL        256
            // RTLD_LOCAL           0

            const libt = libraryType(path);
            let flag = 2; // RTLD_NOW
            if(libt === "local"){
                flag = 2 /* RTLD_NOW */ | 0 /* RTLD_LOCAL */;
            }
            else if(libt === "global"){
                flag = 2 /* RTLD_NOW */ | 256 /* RTLD_GLOBAL */;
            }

            const stack = Module.stackSave();
            const pathUTF8 = Module.stringToUTF8OnStack(path);
            try {
                const pid = Module._emscripten_dlopen_promise(pathUTF8, flag);
                Module.stackRestore(stack);
                const promise = Module.getPromise(pid);
                Module.promiseMap.free(pid);
                await promise;
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

           
        } catch (e) {
            throw e;
        } finally { 
            releaseDynlibLock();
        }

    }
}

Module["_loadDynlibsFromPackage"] = loadDynlibsFromPackage;



