
from pathlib import Path
import json
import sys
import os
import tempfile
import shutil

language_info_js = {
    "name": "javascript",
    "version": "1.0.0",
    "mimetype": "application/javascript",
    "file_extension": ".js",
    "codemirror_mode": "javascript",
    "nbconvert_exporter": "javascript",
    "pygments_lexer": "javascript",
    "jupyterlite": {
        "kernel": "xeus-javascript",
        "spec": "javascript"
    }
}
kernelspec_js = {
    "display_name": "xeus-javascript",
    "language": "javascript",
    "name": "xeus-javascript"
}

metadata_js = {
    "language_info": language_info_js,
    "kernelspec": kernelspec_js
}


language_info_py = {
    "name": "python",
    "version": "3.11.0",
    "mimetype": "text/x-python",
    "file_extension": ".py",
    "codemirror_mode": "python",
    "nbconvert_exporter": "python",
    "pygments_lexer": "python",
}

kernelspec_py = {
    "display_name": "xeus-python",
    "language": "python",
    "name": "xeus-python"
}

metadata_py = {
    "language_info": language_info_py,
    "kernelspec": kernelspec_py
}


def fix_metadata(notebook_path):
    with open(notebook_path, "r") as f:
        notebook = json.load(f) 

    notebook_name = notebook_path.stem
    if notebook_name.startswith("js_"):
        notebook["metadata"] = metadata_js
    elif notebook_name.startswith("py_"):
        notebook["metadata"] = metadata_py
    else:
        print(f"Notebook {notebook_path} does not start with js_ or py_")
    
    with open(notebook_path, "w") as f:
        json.dump(notebook, f, indent=4)

def fix_all_notebooks(directory):
    # iterate over all notebooks (with pathlib)
    for item in Path(directory).iterdir():
        if item.is_file() and item.suffix == ".ipynb":
            fix_metadata(item)


# def fix_rst_links(js_rst_file):

#     # core name without extension
#     core_name = js_rst_file.stem
#     to_replace = f"../lite/lab/?path=auto_examples/{core_name}.js"
#     replacement = f"../lite/lab/?path=auto_examples/{core_name}.ipynb"


#     # read the file
#     with open(js_rst_file, "r") as f:
#         lines = f.readlines()
    
#     # replace the links
#     new_lines = [line.replace(to_replace, replacement) for line in lines]
    
#     # write the file
#     with open(js_rst_file, "w") as f:
#         f.writelines(new_lines)
        
def fix_html_links(js_html_file):

    # core name without extension
    core_name = js_html_file.stem
    to_replace = f"../lite/lab/?path=auto_examples/{core_name}.js"
    replacement = f"../lite/lab/?path=auto_examples/{core_name}.ipynb"


    # read the file
    with open(js_html_file, "r") as f:
        lines = f.readlines()
    
    # replace the links
    new_lines = [line.replace(to_replace, replacement) for line in lines]
    
    # write the file
    with open(js_html_file, "w") as f:
        f.writelines(new_lines)

if __name__ == "__main__":

    from pathlib import Path

    this_dir = Path(__file__)#.parent
    auto_examples_dir = this_dir / "auto_examples"
    build_dir_html = this_dir / "_build" / "html"
    lite_build_dir = build_dir_html / "lite"

    lite_auto_examples_dir = lite_build_dir / "files"/ "auto_examples"

    fix_all_notebooks(lite_auto_examples_dir)
    fix_all_notebooks(auto_examples_dir)

    auto_example_build_dir = build_dir_html / "auto_examples"

    # iterate over all rst files in auto_examples
    # _dir
    for item in auto_example_build_dir.iterdir():
        print(item)
        if item.is_file() and item.suffix == ".html":
            # only for js 
            if item.stem.startswith("js_"):
                print("fixing html links")
                fix_html_links(item)



    lite_build_dir = this_dir / "_build"/ "html" / "lite"
    lite_build_dir.mkdir(parents=True, exist_ok=True)


    # get WASM_ENV_PREFIX  from environment
    env_location = Path(os.environ["WASM_ENV_PREFIX"])
    if not env_location.exists():
        raise ValueError(f"env_location {env_location} does not exist")

   
    pyjs_dir = env_location / "lib_js" / "pyjs"
    shutil.copy(pyjs_dir/"pyjs_runtime_browser.js",   lite_build_dir / "extensions"/ "@jupyterlite"/"xeus"/"static/")
    shutil.copy(pyjs_dir/"pyjs_runtime_browser.wasm", lite_build_dir / "extensions"/ "@jupyterlite"/"xeus"/"static/")

