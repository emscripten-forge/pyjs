work_dir = process.argv[2];
console.log(`work_dir ${work_dir}`);
// require(work_dir+"/pyjs_runtime_node.js")


script_dir = process.argv[3];
script_name = process.argv[4];

console.log(`script_dir ${script_dir}`);
console.log(`script_name ${script_name}`);

(async () => {
    try {   
        const { default: createModule }  = await import(work_dir+"/pyjs_runtime_node.js")
        console.log(createModule())
        


        var pyjs = await createModule()
        var EmscriptenForgeModule = pyjs
        global.EmscriptenForgeModule = pyjs
        global.pyjs = pyjs

        await import(work_dir +'/python_data_node.js')
        await import(work_dir +'/script_data.js')
        await pyjs.init()



        try{
            pyjs.exec("import os")
            pyjs.exec(`os.chdir("${script_dir}")`)
            pyjs.eval_file(`${script_dir}/${script_name}`);
        }
        catch(e){
            console.error("error while evaluating main file:",e)
            return 1;
        }



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
        let ret_code = pyjs.eval("_ret_code[0]");
        if(ret_code != 0)
        {   
            process.exit(ret_code);
        }


    } catch (e) {
       console.error(e)
    }
    // `text` is not available here
})();