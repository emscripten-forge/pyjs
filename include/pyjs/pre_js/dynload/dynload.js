const python_version = {
    major: 3,
    minor: 10
};
const API = {
    python_version: python_version,
    defaultLdLibraryPath: ["/lib", "/usr/lib", "/usr/local/lib"],
    sitepackages: `/lib/python${python_version.major}.${python_version.minor}/site-packages`,
}

const SHARED_LIB_LOCATIONS = new Set()
// for each element in defaultLdLibraryPath
for (const path of API.defaultLdLibraryPath) {
    SHARED_LIB_LOCATIONS.add(path);
}

const memoize = (fn) => {
    let cache = {};
    return (...args) => {
        let n = args[0];
        if (n in cache) {
            return cache[n];
        } else {
            let result = fn(n);
            cache[n] = result;
            return result;
        }
    };
};


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

function isInSharedLibraryPath(libPath){
    if (libPath.startsWith("/")){
        const dirname = libPath.substring(0, libPath.lastIndexOf("/"));
        return SHARED_LIB_LOCATIONS.has(dirname);
    }
    else{
        return false;
    }
}


async function loadDynlibsFromPackage(
    pkg_file_name,
    pkg_is_shared_library,
    dynlibPaths,
  ) {

    // assume that shared libraries of a package are located in <package-name>.libs directory,
    // following the convention of auditwheel.
    const auditWheelLibDir = `${API.sitepackages}/${
        pkg_file_name.split("-")[0]
    }.libs`;
  
    // This prevents from reading large libraries multiple times.
    const readFileMemoized = memoize(Module.FS.readFile);
  
    const forceGlobal = !!pkg_is_shared_library;
    
    //console.log("forceGlobal", forceGlobal,"pkg_is_shared_library", pkg_is_shared_library);

    let dynlibs = [];
  
    if (forceGlobal) {
      dynlibs = dynlibPaths.map((path) => {
        return {
          path: path,
          global: true,
        };
      });
    } else {
      const globalLibs = calculateGlobalLibs(
        dynlibPaths,
        readFileMemoized,
      );

      dynlibs = dynlibPaths.map((path) => {
        const global = globalLibs.has(Module.PATH.basename(path));
        //console.log(`isInSharedLibraryPath ${path} ${isInSharedLibraryPath(path)}`);
        return {
          path: path,
          global: global || !! pkg_is_shared_library || isInSharedLibraryPath(path) || path.startsWith(auditWheelLibDir),
        };
      });
    }
  
    dynlibs.sort((lib1, lib2) => Number(lib2.global) - Number(lib1.global));

    for (const { path, global } of dynlibs) {
      //console.log(`loading dynlib  ${path} global ${global}`);
      await loadDynlib(path, global, [auditWheelLibDir], readFileMemoized);
    }
  }

function createDynlibFS(
    lib,
    searchDirs,
    readFileFunc
) {
    const dirname = lib.substring(0, lib.lastIndexOf("/"));

    let _searchDirs = searchDirs || [];
    _searchDirs = _searchDirs.concat([dirname], API.defaultLdLibraryPath,);

    const resolvePath = (path) => {
        //console.log("resolvePath", path);
        
        if (Module.PATH.basename(path) !== Module.PATH.basename(lib)) {
            //console.debug(`Searching a library from ${path}, required by ${lib}`);
        }

        for (const dir of _searchDirs) {
            const fullPath = Module.PATH.join2(dir, path);
            //console.log("SERARCHING", fullPath);
            if (Module.FS.findObject(fullPath) !== null) {
                return fullPath;
            }
        }
        return path;
    };

    let readFile = (path) =>
        Module.FS.readFile(resolvePath(path));

    if (readFileFunc !== undefined) {
        readFile = (path) => readFileFunc(resolvePath(path));
    }

    const fs = {
        findObject: (path, dontResolveLastLink) => {
            let obj = Module.FS.findObject(resolvePath(path), dontResolveLastLink);

            if (obj === null) {
                console.debug(`Failed to find a library: ${resolvePath(path)}`);
            }

            return obj;
        },
        readFile: readFile,
    };

    return fs;
}


function calculateGlobalLibs(
    libs,
    readFileFunc
) {
    let readFile = Module.FS.readFile;
    if (readFileFunc !== undefined) {
        readFile = readFileFunc;
    }

    const globalLibs = new Set();

    libs.forEach((lib) => {
        const binary = readFile(lib);
        const needed = Module.getDylinkMetadata(binary).neededDynlibs;
        needed.forEach((lib) => {
            globalLibs.add(lib);
        });
    });

    return globalLibs;
}


// Emscripten has a lock in the corresponding code in library_browser.js. I
// don't know why we need it, but quite possibly bad stuff will happen without
// it.
const acquireDynlibLock = createLock();

async function loadDynlib(lib, global, searchDirs, readFileFunc) {
    if (searchDirs === undefined) {
        searchDirs = [];
    }
    const releaseDynlibLock = await acquireDynlibLock();

    try {
        const fs = createDynlibFS(lib, searchDirs, readFileFunc);

        const libName = Module.PATH.basename(lib);
        //console.log("load lib", lib);
        //console.log(`libName ${libName}`)

        await Module.loadDynamicLibrary(libName, {
            loadAsync: true,
            nodelete: true,
            allowUndefined: true,
            global: global,
            fs: fs
        })
        
        const dsoOnlyLibName = Module.LDSO.loadedLibsByName[libName];
        const dsoFullLib = Module.LDSO.loadedLibsByName[lib];

        if(!dsoOnlyLibName && !dsoFullLib){
            console.execption(`Failed to load ${libName} from ${lib} LDSO not found`);
        }

        if (!dsoOnlyLibName) {
            
            Module.LDSO.loadedLibsByName[libName] = dsoFullLib
        }
        
        if(!dsoFullLib){
            Module.LDSO.loadedLibsByName[lib] = dsoOnlyLibName;
        }
    } finally {
        releaseDynlibLock();
    }
}

Module["_loadDynlibsFromPackage"] = loadDynlibsFromPackage;



