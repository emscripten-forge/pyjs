// from https://zlib.net/zlib_how.html
// and https://windrealm.org/tutorials/decompress-gzip-stream.php
// and https://stackoverflow.com/questions/10195343/copy-a-file-in-a-sane-safe-and-efficient-way
#pragma once

#include <stdio.h>
#include <string.h>
#include <assert.h>
#include "zlib.h"

#define CHUNK 16384

namespace pyjs{



/* Decompress from file source to file dest until stream ends or EOF. */
void inflate(gzFile_s  *source, FILE *dest) {

  unsigned char buf[CHUNK];

  for (
    int size = gzread(source, buf, CHUNK);
    size > 0;
    size = gzread(source, buf, CHUNK)
  ) {
        fwrite(buf, 1, CHUNK, dest);
  }

}

}