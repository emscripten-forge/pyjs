# fake a python executable
import argparse




def run_cmd(args):

    parser = argparse.ArgumentParser()

    # -c command
    parser.add_argument("-c", help="run the python command", type=str)

    args = parser.parse_args(args)

    if args.c:
        cmd = args.c
        cmd = cmd.strip()

        # if the command is sourrounded by quotes, remove them
        if (cmd[0] == '"' and cmd[-1] == '"') or (cmd[0] == "'" and cmd[-1] == "'"):
            cmd = cmd[1:-1]
        
        print(f"running command: {cmd}")
        exec(cmd)
   
    # return code
    return 0



if __name__ == "__main__":
    run_cmd(['''-c "a=1+1;print(a)"'''])