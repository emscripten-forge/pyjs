from pathlib import Path
import sys

header = """
#include "pyjs/macro_magic.hpp"
BEGIN_PYTHON_INIT({module_name}) R"pycode(#"
"""

footer = """
#)pycode"
END_PYTHON_INIT
"""

def generate_embed(fn_in, fn_out):
	fn_in = Path(fn_in)
	fn = fn_in.name
	modname = "pyjs_" + fn.split('.')[0]
	text = fn_in.read_text()
	res = header.format(module_name=modname) + text + footer
	fn_out = Path(fn_out)
	fn_out.write_text(res)

if __name__ == "__main__":
	generate_embed(sys.argv[1], sys.argv[2])