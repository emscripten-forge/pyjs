





Module["_parallel_fetch_array_buffer"] = async function (urls){
    let promises = urls.map(url => fetch(url).then(response => response.arrayBuffer()));
    return await Promise.all(promises);
}

Module["_parallel_fetch_arraybuffers_with_progress_bar"] = async function (urls, done_callback, progress_callback){
    if(done_callback === undefined || done_callback === null){
        done_callback = async function(
            index, byte_array
        ){};
    }

    if(progress_callback===undefined || progress_callback===null)
    {   

        let f = async function(index){
            let res = await fetch(urls[index]);
            if (!res.ok) {
                throw new Error(`HTTP error! when fetching ${urls[index]} status: ${res.status}`);
            }
            const arrayBuffer = await res.arrayBuffer();
            const byteArray = new Uint8Array(arrayBuffer);
            await done_callback(index, byteArray);
            return byteArray;
        }
        let futures = []
        for(let i=0;i<urls.length;i++){
            futures.push(f(i))
        }
        return await Promise.all(futures);
    }
    
    async function fetch_arraybuffer_with_progress_bar(url,index, report_total_length,report_progress, report_finished){
        let response = await fetch(url);
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }        
        const reader = response.body.getReader();

        // Step 2: get total length
        const contentLength = +response.headers.get('Content-Length');
        report_total_length(index, contentLength);
        // Step 3: read the data
        let receivedLength = 0; // received that many bytes at the moment
        let chunks = []; // array of received binary chunks (comprises the body)
        while(true) {
            const {done, value} = await reader.read();
            if (done) {
                report_finished(index);
                break;
            }
            chunks.push(value);
            receivedLength += value.length;
            report_progress(index, receivedLength);
        }
        // Step 4: concatenate chunks into single Uint8Array
        let chunksAll = new Uint8Array(receivedLength); // (4.1)
        let position = 0;
        for(let chunk of chunks) {
            chunksAll.set(chunk, position); // (4.2)
            position += chunk.length;
        }
        await done_callback(index, chunksAll);
        return chunksAll
    }
    let n_urls = urls.length;
    let receivedArr = Array(n_urls).fill(0);
    let totalArr = Array(n_urls).fill(0);
    let finishedArr = Array(n_urls).fill(0);
    function on_progress(){
        let total = totalArr.reduce((partialSum, a) => partialSum + a, 0);
        let recived = receivedArr.reduce((partialSum, a) => partialSum + a, 0);
        let n_finished = finishedArr.reduce((partialSum, a) => partialSum + a, 0);
        
        if(progress_callback !== undefined){
            progress_callback(recived,total,n_finished, n_urls);
        }
    }
    
    function report_finished(index){
        finishedArr[index] = 1;
        on_progress();
    }
         
    function report_total_length(index, total){
        totalArr[index] = total;
        on_progress();
    }
    function report_progress(index, p){
        receivedArr[index] = p;
        on_progress();
    }
    
    let futures = urls.map((url, index) => {
        return fetch_arraybuffer_with_progress_bar(url,index, report_total_length,report_progress, report_finished)
    })
    return await Promise.all(futures);
}


Module["fetch_and_untar"] = async function(
    urls,
    filenames,
    extract_to,
    verbose=false,
){
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

    let shared_libs = new Array(urls.length)

    let done_callback = async function(i, byte_array){
        log("finished download",filenames[i])

        // get dirname from filename
        let dirname = filenames[i].split("/").slice(0,-1).join("/")
        Module.mkdirs(dirname);

        // get filename without directory
        let filename = filenames[i].split("/").slice(-1)[0]
        

        log("writing",filenames[i])
        Module.FS.writeFile(filenames[i], byte_array);

        log("untar", filenames[i])
        shared_libs[i] = Module._untar(filenames[i], extract_to[i]);
    }

    await Module._parallel_fetch_arraybuffers_with_progress_bar(urls,done_callback, progress_callback)


    for(let i=0;i<urls.length;i++){
        if(shared_libs[i].length > 0){
            await Module._loadDynlibsFromPackage(
                filenames[i],
                false,
                shared_libs[i]
            )
        }  
    }
}