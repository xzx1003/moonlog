/* Only OS byte I/O. Parsing, line splitting, statistics and reports live in MoonBit. */
#include <stdio.h>
#include <stdlib.h>
#include <errno.h>
#include <string.h>
#include <sys/stat.h>
#include "moonbit.h"

MOONBIT_FFI_EXPORT FILE *moonlog_open(moonbit_bytes_t path, int output) {
  FILE *f = fopen((const char *)path, output ? "wbx" : "rb");
  if (!f) return NULL;
  struct stat st;
  if (fstat(fileno(f), &st) != 0 || !S_ISREG(st.st_mode)) {
    fclose(f);
    errno = EINVAL;
    return NULL;
  }
  return f;
}
MOONBIT_FFI_EXPORT int moonlog_null(FILE *f) { return f == NULL; }
MOONBIT_FFI_EXPORT int moonlog_read(FILE *f, moonbit_bytes_t bytes, int size) {
  size_t n = fread(bytes, 1, (size_t)size, f);
  return ferror(f) ? -1 : (int)n;
}
MOONBIT_FFI_EXPORT int moonlog_write(FILE *f, moonbit_bytes_t bytes, int size) {
  return fwrite(bytes, 1, (size_t)size, f) == (size_t)size ? 0 : -1;
}
MOONBIT_FFI_EXPORT int moonlog_close(FILE *f) { return fclose(f); }
MOONBIT_FFI_EXPORT moonbit_bytes_t moonlog_error(void) {
  const char *s = strerror(errno);
  int n = (int)strlen(s);
  moonbit_bytes_t out = moonbit_make_bytes(n, 0);
  memcpy(out, s, n);
  return out;
}
MOONBIT_FFI_EXPORT void moonlog_stderr(moonbit_bytes_t bytes, int size) {
  (void)fwrite(bytes, 1, (size_t)size, stderr);
}
