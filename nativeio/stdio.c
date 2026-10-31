/* Only OS byte I/O. Parsing, line splitting, statistics and reports live in MoonBit. */
#include <stdio.h>
#include <stdlib.h>
#include <errno.h>
#include <string.h>
#include <sys/stat.h>
#include <stdint.h>
#include "moonbit.h"

#ifdef _WIN32
#include <windows.h>
#include <io.h>
#include <fcntl.h>

struct windows_file_id {
  DWORD volume_serial;
  DWORD file_index_high;
  DWORD file_index_low;
};

static wchar_t *utf8_to_wide(const char *utf8) {
  int len = MultiByteToWideChar(CP_UTF8, 0, utf8, -1, NULL, 0);
  if (len == 0) return NULL;
  wchar_t *wide = (wchar_t *)malloc(len * sizeof(wchar_t));
  if (!wide) return NULL;
  if (MultiByteToWideChar(CP_UTF8, 0, utf8, -1, wide, len) == 0) {
    free(wide);
    return NULL;
  }
  return wide;
}

static int get_windows_file_id(HANDLE h, struct windows_file_id *id) {
  BY_HANDLE_FILE_INFORMATION info;
  if (!GetFileInformationByHandle(h, &info)) return -1;
  id->volume_serial = info.dwVolumeSerialNumber;
  id->file_index_high = info.nFileIndexHigh;
  id->file_index_low = info.nFileIndexLow;
  return 0;
}

static int is_regular_file_windows(HANDLE h) {
  DWORD type = GetFileType(h);
  if (type == FILE_TYPE_DISK) {
    BY_HANDLE_FILE_INFORMATION info;
    if (GetFileInformationByHandle(h, &info)) {
      return (info.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) == 0;
    }
  }
  return 0;
}

MOONBIT_FFI_EXPORT FILE *moonlog_open(moonbit_bytes_t path, int output) {
  wchar_t *wpath = utf8_to_wide((const char *)path);
  if (!wpath) return NULL;
  
  FILE *f = NULL;
  if (output) {
    HANDLE h = CreateFileW(wpath, GENERIC_WRITE, 0, NULL, CREATE_NEW, FILE_ATTRIBUTE_NORMAL, NULL);
    if (h == INVALID_HANDLE_VALUE) {
      free(wpath);
      if (GetLastError() == ERROR_FILE_EXISTS) errno = EEXIST;
      else errno = EIO;
      return NULL;
    }
    int fd = _open_osfhandle((intptr_t)h, _O_WRONLY);
    if (fd == -1) {
      CloseHandle(h);
      free(wpath);
      errno = EIO;
      return NULL;
    }
    f = _fdopen(fd, "wb");
    if (!f) {
      _close(fd);
      free(wpath);
      errno = EIO;
      return NULL;
    }
  } else {
    f = _wfopen(wpath, L"rb");
    if (!f) {
      free(wpath);
      return NULL;
    }
  }
  
  int fd = _fileno(f);
  HANDLE h = (HANDLE)_get_osfhandle(fd);
  if (h == INVALID_HANDLE_VALUE || !is_regular_file_windows(h)) {
    fclose(f);
    free(wpath);
    errno = EINVAL;
    return NULL;
  }
  
  free(wpath);
  return f;
}

MOONBIT_FFI_EXPORT int moonlog_same_file(moonbit_bytes_t a, moonbit_bytes_t b) {
  wchar_t *wa = utf8_to_wide((const char *)a);
  wchar_t *wb = utf8_to_wide((const char *)b);
  if (!wa || !wb) { free(wa); free(wb); return 0; }
  
  FILE *fa = _wfopen(wa, L"rb");
  FILE *fb = _wfopen(wb, L"rb");
  free(wa);
  free(wb);
  
  if (!fa || !fb) {
    if (fa) fclose(fa);
    if (fb) fclose(fb);
    return 0;
  }
  
  HANDLE ha = (HANDLE)_get_osfhandle(_fileno(fa));
  HANDLE hb = (HANDLE)_get_osfhandle(_fileno(fb));
  struct windows_file_id id_a, id_b;
  int result = 0;
  
  if (get_windows_file_id(ha, &id_a) == 0 && get_windows_file_id(hb, &id_b) == 0) {
    result = (id_a.volume_serial == id_b.volume_serial &&
              id_a.file_index_high == id_b.file_index_high &&
              id_a.file_index_low == id_b.file_index_low);
  }
  
  fclose(fa);
  fclose(fb);
  return result;
}

MOONBIT_FFI_EXPORT moonbit_bytes_t moonlog_stat(moonbit_bytes_t path) {
  wchar_t *wpath = utf8_to_wide((const char *)path);
  if (!wpath) return moonbit_make_bytes(0, 0);
  
  FILE *f = _wfopen(wpath, L"rb");
  free(wpath);
  if (!f) return moonbit_make_bytes(0, 0);
  
  HANDLE h = (HANDLE)_get_osfhandle(_fileno(f));
  if (!is_regular_file_windows(h)) {
    fclose(f);
    errno = EINVAL;
    return moonbit_make_bytes(0, 0);
  }
  
  struct windows_file_id id;
  if (get_windows_file_id(h, &id) != 0) {
    fclose(f);
    return moonbit_make_bytes(0, 0);
  }
  fclose(f);
  
  char buf[64];
  int n = snprintf(buf, sizeof(buf), "%lu:%lu:%lu", id.volume_serial, id.file_index_high, id.file_index_low);
  if (n < 0 || (size_t)n >= sizeof(buf)) {
    errno = EOVERFLOW;
    return moonbit_make_bytes(0, 0);
  }
  moonbit_bytes_t out = moonbit_make_bytes(n, 0);
  memcpy(out, buf, (size_t)n);
  return out;
}

MOONBIT_FFI_EXPORT int moonlog_make_directory(moonbit_bytes_t path) {
  wchar_t *wpath = utf8_to_wide((const char *)path);
  if (!wpath) {
    errno = EINVAL;
    return -1;
  }
  if (CreateDirectoryW(wpath, NULL)) {
    free(wpath);
    return 0;
  }
  DWORD error = GetLastError();
  if (error == ERROR_ALREADY_EXISTS) {
    DWORD attributes = GetFileAttributesW(wpath);
    free(wpath);
    if (attributes != INVALID_FILE_ATTRIBUTES &&
        (attributes & FILE_ATTRIBUTE_DIRECTORY) != 0) {
      return 0;
    }
    errno = EEXIST;
    return -1;
  }
  free(wpath);
  errno = EIO;
  return -1;
}

#else
/* POSIX implementation */

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

MOONBIT_FFI_EXPORT int moonlog_same_file(moonbit_bytes_t a, moonbit_bytes_t b) {
  struct stat sa, sb;
  if (stat((const char *)a, &sa) != 0 || stat((const char *)b, &sb) != 0) {
    return 0;
  }
  return sa.st_dev == sb.st_dev && sa.st_ino == sb.st_ino;
}

MOONBIT_FFI_EXPORT moonbit_bytes_t moonlog_stat(moonbit_bytes_t path) {
  struct stat st;
  if (stat((const char *)path, &st) != 0) {
    return moonbit_make_bytes(0, 0);
  }
  if (!S_ISREG(st.st_mode)) {
    errno = EINVAL;
    return moonbit_make_bytes(0, 0);
  }
  char buf[64];
  int n = snprintf(buf, sizeof(buf), "%llu:%llu",
                   (unsigned long long)st.st_dev,
                   (unsigned long long)st.st_ino);
  if (n < 0 || (size_t)n >= sizeof(buf)) {
    errno = EOVERFLOW;
    return moonbit_make_bytes(0, 0);
  }
  moonbit_bytes_t out = moonbit_make_bytes(n, 0);
  memcpy(out, buf, (size_t)n);
  return out;
}


MOONBIT_FFI_EXPORT int moonlog_make_directory(moonbit_bytes_t path) {
  struct stat st;
  if (stat((const char *)path, &st) == 0) {
    if (S_ISDIR(st.st_mode)) return 0;
    errno = EEXIST;
    return -1;
  }
  return mkdir((const char *)path, 0700);
}

#endif

/* Common functions for both platforms */
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
