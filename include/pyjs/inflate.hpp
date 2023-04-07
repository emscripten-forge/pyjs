

#include "zlib.h"

namespace pyjs{

    /* Decompress from file source to file dest until stream ends or EOF. */
    void inflate(gzFile_s  *source, FILE *dest);

}