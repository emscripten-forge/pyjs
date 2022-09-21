import sys


def merge(*filenames):
    filenames_in = filenames[0:-1]
    filename_out = filenames[-1]
    print("filenames_in", filenames_in)
    print("filename_out", filename_out)
    with open(filename_out, "w") as outfile:
        for fname in filenames_in:
            with open(fname) as infile:
                for line in infile:
                    outfile.write(line)
            outfile.write("\n")


if __name__ == "__main__":
    merge(*sys.argv[1:])
