async function make_pyjs(print, error) {
    var pyjs = await createModule({print:print,error:print})
    var EmscriptenForgeModule = pyjs
    globalThis.EmscriptenForgeModule = pyjs
    globalThis.pyjs = pyjs

    await import('./python_data.js')
    await import('./script_data.js')
    await pyjs.init()

    return pyjs
}

globalThis.make_pyjs = make_pyjs



function eval_main_script(pyjs, workdir, filename) {
    try{
        pyjs.exec("import os")
        pyjs.exec(`os.chdir("${workdir}")`)
        pyjs.eval_file(filename);
        return 0;
    }
    catch(e){
        console.error("error while evaluating main file:",e)
        return 1;
    }
    return 0
}
globalThis.eval_main_script = eval_main_script

async function run_async_python_main(pyjs) {


    pyjs.exec(`
import asyncio
_async_done_ = [False]
_ret_code = [0]
async def main_runner():
    try:
        _ret_code[0] = await main()
    except Exception as e:
        _ret_code[0] = 1
        print("EXCEPTION",e)
    finally:
        global _async_done_
        _async_done_[0] = True
asyncio.ensure_future(main_runner())
    `)

    while(true)
    {
        await new Promise(resolve => setTimeout(resolve, 100));
        const _async_done_ = pyjs.eval("_async_done_[0]")
        if(_async_done_)
        {
            break;
        }
    }
    return pyjs.eval("_ret_code[0]")
                
}
globalThis.run_async_python_main = run_async_python_main

// export { make_pyjs, run_async_python_main, eval_main_script };


if (typeof exports === 'object' && typeof module === 'object'){
    console.log("A")
  module.exports = make_pyjs;
}
else if (typeof define === 'function' && define['amd']){
    console.log("B")
  define([], function() { return make_pyjs; });
}
else if (typeof exports === 'object'){
    console.log("C")
  exports["make_pyjs"] = make_pyjs;
}
// else{
//     console.log("D")
//     export { make_pyjs, run_async_python_main, eval_main_script };
// }