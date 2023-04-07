Module["mkdirs"] = function (dirname) {
   // get all partent directories
   let parent_dirs = []
   let parent_dir = dirname
   while(parent_dir != ""){
       parent_dirs.push(parent_dir)
       parent_dir = parent_dir.split("/").slice(0,-1).join("/")
   }
   // make directories
   parent_dirs = parent_dirs.reverse()
   for(let parent_dir of parent_dirs){
       if(!Module.FS.isDir(parent_dir)){
           Module.FS.mkdir(parent_dir)
       }
   }
}


Module["load_empack_packed_environment"] = async function
(
    packages_json_url,
    package_tarballs_root_url,
    verbose=false
) {
    let log = function(...args){
        if(verbose){
            console.log(...args)
        }
    }
    let progress_callback = undefined
    if (verbose){
        progress_callback = function(n_bytes, total_bytes, ...args){
            console.log(`fetching ${n_bytes} of ${total_bytes} bytes`)
        }
    }
        
    log("load_empack_packed_environment",packages_json_url)
    log(`loading package.json from ${packages_json_url}`)

    let res = await fetch(packages_json_url)
    if (!res.ok) {
        throw new Error(`HTTP error! status: ${res.status}`);
    }
    let packages = await res.json()
    let urls = packages.map(item => `${package_tarballs_root_url}/${item.filename}`)

    // create array with size 
    let shared_libs = new Array(urls.length)
    Module.mkdirs(`/package_tarballs`);

    let done_callback = async function(i, byte_array){
        log("writing",packages[i].filename)
        const tarball_path = `/package_tarballs/${packages[i].filename}`;
        Module.FS.writeFile(tarball_path, byte_array);

        log("untar", packages[i].filename)
        shared_libs[i] = Module._untar(tarball_path, "/");;
    }

    await Module._parallel_fetch_arraybuffers_with_progress_bar(urls,done_callback, progress_callback)


    log("untar done, instantiating packages")
    // instantiate all packages
    for(let i=0;i<urls.length;i++){


        log("instantiating",packages[i].name)
        // if we have any shared libraries, load them
        if(shared_libs[i].length > 0){
            await Module._loadDynlibsFromPackage(
                packages[i].name,
                false,
                shared_libs[i]
            )
        }        
    }
    log("instantiating packages done")
}