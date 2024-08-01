# fake a python executable
import argparse
import traceback 
from .convert import to_py
from pyjs_core import JsValue

def run_cmd(args):


    if isinstance(args, JsValue):
        args = to_py(args)
    
    if not isinstance(args, list):
        raise TypeError("args should be a list")

    parser = argparse.ArgumentParser(
        description="A Python script with various command-line options.",
        usage='python [option] ... [-c cmd | -m mod | file | -] [arg] ...',
        add_help=False
    )

    # Options
    parser.add_argument('-b', action='store_true', help='Issue warnings about converting bytes/bytearray to str and comparing bytes/bytearray with str or bytes with int. (-bb: issue errors)')
    parser.add_argument('-B', action='store_true', help="Don't write .pyc files on import; also PYTHONDONTWRITEBYTECODE=x")
    parser.add_argument('-c', metavar='cmd', help='Program passed in as string (terminates option list)')
    parser.add_argument('-d', action='store_true', help='Turn on parser debugging output (for experts only, only works on debug builds); also PYTHONDEBUG=x')
    parser.add_argument('-E', action='store_true', help='Ignore PYTHON* environment variables (such as PYTHONPATH)')
    parser.add_argument('-h','--help', action='store_true', help='Print this help message and exit (also -? or --help)')
    parser.add_argument('-i', action='store_true', help='Inspect interactively after running script; forces a prompt even if stdin does not appear to be a terminal; also PYTHONINSPECT=x')
    parser.add_argument('-I', action='store_true', help="Isolate Python from the user's environment (implies -E and -s)")
    parser.add_argument('-m', metavar='mod', help='Run library module as a script (terminates option list)')
    parser.add_argument('-O', action='store_true', help='Remove assert and __debug__-dependent statements; add .opt-1 before .pyc extension; also PYTHONOPTIMIZE=x')
    parser.add_argument('-OO', action='store_true', help='Do -O changes and also discard docstrings; add .opt-2 before .pyc extension')
    parser.add_argument('-P', action='store_true', help="Don't prepend a potentially unsafe path to sys.path; also PYTHONSAFEPATH")
    parser.add_argument('-q', action='store_true', help="Don't print version and copyright messages on interactive startup")
    parser.add_argument('-s', action='store_true', help="Don't add user site directory to sys.path; also PYTHONNOUSERSITE=x")
    parser.add_argument('-S', action='store_true', help="Don't imply 'import site' on initialization")
    parser.add_argument('-u', action='store_true', help='Force the stdout and stderr streams to be unbuffered; this option has no effect on stdin; also PYTHONUNBUFFERED=x')
    parser.add_argument('-v', action='count', help='Verbose (trace import statements); also PYTHONVERBOSE=x. Can be supplied multiple times to increase verbosity')
    parser.add_argument('-V', '--version', action='store_true', help='Print the Python version number and exit. When given twice, print more information about the build')
    parser.add_argument('-W', metavar='arg', help='Warning control; arg is action:message:category:module:lineno. Also PYTHONWARNINGS=arg')
    parser.add_argument('-x', action='store_true', help='Skip first line of source, allowing use of non-Unix forms of #!cmd')
    parser.add_argument('-X', metavar='opt', help='Set implementation-specific option')
    parser.add_argument('--check-hash-based-pycs', choices=['always', 'default', 'never'], help='Control how Python invalidates hash-based .pyc files')
    parser.add_argument('--help-env', action='store_true', help='Print help about Python environment variables and exit')
    parser.add_argument('--help-xoptions', action='store_true', help='Print help about implementation-specific -X options and exit')
    parser.add_argument('--help-all', action='store_true', help='Print complete help information and exit')

    # Arguments
    parser.add_argument('file', nargs='?', help='Program read from script file')
    parser.add_argument('-', dest='stdin', action='store_true', help='Program read from stdin (default; interactive mode if a tty)')
    parser.add_argument('args', nargs=argparse.REMAINDER, help='Arguments passed to program in sys.argv[1:]')

   
    parsed_args = parser.parse_args(args)
    # print(parsed_args)
    
    if  parsed_args.help or parsed_args.help_env or parsed_args.help_xoptions or parsed_args.help_all:
        parser.print_help()
        return 0
    
    if parsed_args.version:
        import sys
        print(sys.version)
        return 0

    if parsed_args.c:
        cmd = parsed_args.c
        cmd = cmd.strip()

        # if the command is sourrounded by quotes, remove them
        if (cmd[0] == '"' and cmd[-1] == '"') or (cmd[0] == "'" and cmd[-1] == "'"):
            cmd = cmd[1:-1]
        try:
            exec(cmd)
        except Exception as e:
            # print Exception traceback
            import traceback    
            print(traceback.format_exc())
            return 1
        return 0

    return 1

# if __name__ == "__main__":
#     from contextlib import redirect_stdout

#     with io.StringIO() as buf, redirect_stdout(buf):
#         ret = run_cmd(['-h'])
#         assert ret == 0
#         assert "usage" in buf.getvalue()
    
#     with io.StringIO() as buf, redirect_stdout(buf):
#         ret = run_cmd(['-V'])
#         assert ret == 0
#         assert "3." in buf.getvalue()
    
#     with io.StringIO() as buf, redirect_stdout(buf):
#         ret = run_cmd(['-c', 'a=1+1;print(a)'])
#         assert ret == 0
#         ret = str(buf.getvalue())
#         assert buf.getvalue() == "2\n"


