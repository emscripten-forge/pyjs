import sys
import datetime


def merge(*filenames):
    filenames = list(filenames)
    filename_timestamp = filenames.pop()
    filename_out = filenames.pop()
    filenames_in = filenames

    print("filenames_in", filenames_in)
    print("filename_out", filename_out)
    print("filename_timestamp", filename_timestamp)
    with open(filename_out, "w") as outfile:
        for fname in filenames_in:
            with open(fname) as infile:
                for line in infile:
                    outfile.write(line)
            outfile.write("\n")

    with open(filename_timestamp, "w") as outfile:
        timestamp = str(datetime.datetime.utcnow())
        outfile.write(f'#define PYJS_JS_UTC_TIMESTAMP "{timestamp}"')


if __name__ == "__main__":
    print("merging js files:")
    merge(*sys.argv[1:])
