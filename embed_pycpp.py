import sys
from pathlib import Path

template = """
void {name}_pseudo_init(py::module_& m){{

    py::object scope = m.attr("__dict__");
    py::exec(R"(
{content}
)");

}}
"""


def generate_embed(fn_in, fn_out):
    fn_in = Path(fn_in)
    fn = fn_in.name
    modname = "pyjs_" + fn.split(".")[0]
    content = fn_in.read_text()
    res = template.format(name=modname, content=content)
    fn_out = Path(fn_out)
    fn_out.write_text(res)


if __name__ == "__main__":
    print(sys.argv[1], sys.argv[2])
    generate_embed(sys.argv[1], sys.argv[2])
