Module["mkdirs"] = function (dirname) {
    // get all partent directories
    let parent_dirs = []
    let parent_dir = dirname
    while (parent_dir != "") {
        parent_dirs.push(parent_dir)
        parent_dir = parent_dir.split("/").slice(0, -1).join("/")
    }
    console.log(parent_dirs)
    // make directories
    parent_dirs = parent_dirs.reverse()
    for (let parent_dir of parent_dirs) {
        if (!Module.FS.isDir(parent_dir)) {
            Module.FS.mkdir(parent_dir)
        }
    }
}



Module["_untar_from_python"] = function(tarball_path, target_dir = "") {
    Module.exec(`
def _py_untar(tarball_path, target_dir):
    import tarfile
    import json
    from pathlib import Path
    import tempfile
    import shutil
    import os
    import sys


    def check_wasm_magic_number(file_path: Path) -> bool:
        WASM_BINARY_MAGIC = b"\\0asm"
        with file_path.open(mode="rb") as file:
            return file.read(4) == WASM_BINARY_MAGIC

        
    target_dir = target_dir
    if target_dir == "":
        target_dir = sys.prefix
    try:
        with tarfile.open(tarball_path) as tar:
            files = tar.getmembers()
            shared_libs = []
            for file in files:
                if file.name.endswith(".so"):
                
                    if target_dir == "/":
                        shared_libs.append(f"/{file.name}")
                    else:
                        shared_libs.append(f"{target_dir}/{file.name}")

            tar.extractall(target_dir)
            for file in shared_libs:
                if not check_wasm_magic_number(Path(file)):
                    print(f" {file} is not a wasm file")
            s = json.dumps(shared_libs)
    except Exception as e:
        print("ERROR",e)
        raise e
    return s
`)
    let shared_libs = Module.eval(`_py_untar("${tarball_path}", "${target_dir}")`)

    return JSON.parse(shared_libs)
}






Module["bootstrap_from_empack_packed_environment"] = async function
    (   
        packages_json_url,
        package_tarballs_root_url,
        verbose = true,
        skip_loading_shared_libs = false
    ) 
{
    try{
    
        verbose=true;

        function splitPackages(packages) {
            // find package with name "python" and remove it from the list
            let python_package = undefined
            for (let i = 0; i < packages.length; i++) {
                if (packages[i].name == "python") {
                    python_package = packages[i]
                    packages.splice(i, 1)
                    break
                }
            }
            if (python_package == undefined) {
                throw new Error("no python package found in package.json")
            }
            return { python_package, packages }
        }
        

        
        async function fetchAndUntar
            (
                package_tarballs_root_url,
                python_is_ready_promise,
                pkg,
                verbose
            ) {
            let package_url = pkg?.url ? pkg.url :`${package_tarballs_root_url}/${pkg.filename}`
            if (verbose) {
                console.log(`!!fetching pkg ${pkg.name} from ${package_url}`)
            }
            let byte_array = await fetchByteArray(package_url)
            const tarball_path = `/package_tarballs/${pkg.filename}`;
            Module.FS.writeFile(tarball_path, byte_array);
            if(verbose){
                console.log(`!!extract ${tarball_path} (${byte_array.length} bytes)`)
            }
            if(verbose){console.log("await python_is_ready_promise");}     
            await python_is_ready_promise;
            return Module["_untar_from_python"](tarball_path);
        }

        
        async function bootstrap_python(prefix, package_tarballs_root_url, python_package, verbose) {
            // fetch python package
            let python_package_url = python_package?.url ? python_package.url : `${package_tarballs_root_url}/${python_package.filename}`
        
            if (verbose) {
                console.log(`fetching python package from ${python_package_url}`)
            }
            let byte_array = await fetchByteArray(python_package_url)
        
            const python_tarball_path = `/package_tarballs/${python_package.filename}`;
            if(verbose){
                console.log(`extract ${python_tarball_path} (${byte_array.length} bytes)`)
            }
            Module.FS.writeFile(python_tarball_path, byte_array);
            if(verbose){console.log("untar_from_python");}
            Module._untar(python_tarball_path, prefix);
            
            
        
        
        
            // split version string into major and minor and patch version
            let version = python_package.version.split(".").map(x => parseInt(x));
        
        
            if(verbose){console.log("start init_phase_1");}
            await Module.init_phase_1(prefix, version, verbose);
        }
        
        
        
        if(verbose){
            console.log("fetching packages.json from", packages_json_url)
        }

        // fetch json with list of all packages
        let empack_env_meta = await fetchJson(packages_json_url);
        let all_packages = empack_env_meta.packages;
        let prefix = empack_env_meta.prefix;

        if(verbose){
            console.log("makeDirs");
        }
        Module.create_directories("/package_tarballs");
        
        // enusre there is python and split it from the rest
        if(verbose){console.log("splitPackages");}
        let splitted = splitPackages(all_packages);
        let packages = splitted.packages;
        let python_package = splitted.python_package;
        let python_version = python_package.version.split(".").map(x => parseInt(x));

        // fetch init python itself
        console.log("--bootstrap_python");
        if(verbose){
            console.log("bootstrap_python");
        }
        let python_is_ready_promise = bootstrap_python(prefix, package_tarballs_root_url, python_package, verbose);

        // create array with size 
        if(verbose){
            console.log("fetchAndUntarAll");
        }
        let shared_libs = await Promise.all(packages.map(pkg => fetchAndUntar(package_tarballs_root_url, python_is_ready_promise, pkg, verbose)));

        if(verbose){
            console.log("init_phase_2");
        }       
        Module.init_phase_2(prefix, python_version, verbose);

        if(verbose){
            console.log("init shared");
        }     
        if(!skip_loading_shared_libs){
            // instantiate all packages
            for (let i = 0; i < packages.length; i++) {

                // if we have any shared libraries, load them
                if (shared_libs[i].length > 0) {

                    for (let j = 0; j < shared_libs[i].length; j++) {
                        let sl = shared_libs[i][j];
                    }
                    await Module._loadDynlibsFromPackage(
                        prefix,
                        python_version,
                        packages[i].name,
                        false,
                        shared_libs[i]
                    )
                }
            }
        }
        if(verbose){
            console.log("done bootstrapping");}         
    }
    catch(e){
        console.log("error in bootstrapping process")
        console.error(e);
    }
}