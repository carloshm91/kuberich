/* Owned synthetic auth/exec helper: no Python interpreter or provider account. */
#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

extern char **environ;

int main(int argc, char **argv) {
    for (char **item = environ; *item != NULL; item++) {
        if (strncmp(*item, "_PYI_", 5) == 0) return 71;
    }
    const char *bundle = getenv("OWNED_NATIVE_BUNDLE");
    const char *library_vars[] = {"LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH", "DYLD_FALLBACK_LIBRARY_PATH"};
    for (size_t index = 0; index < sizeof(library_vars) / sizeof(library_vars[0]); index++) {
        const char *libraries = getenv(library_vars[index]);
        if (bundle != NULL && libraries != NULL && strstr(libraries, bundle) != NULL) return 72;
    }
    if (strstr(argv[0], "owned-auth") != NULL) {
        if (argc != 2 || getenv("KUBERNETES_EXEC_INFO") == NULL) return 73;
        FILE *marker = fopen(argv[1], "a");
        if (marker == NULL) return 74;
        fputs("native auth helper called with sanitized loader environment\n", marker);
        if (fclose(marker) != 0) return 75;
        puts("{\"apiVersion\":\"client.authentication.k8s.io/v1\",\"kind\":\"ExecCredential\",\"status\":{\"token\":\"synthetic-pty\"}}");
        return 0;
    }
    if (argc < 10 || strncmp(argv[1], "--kubeconfig=", 13) != 0 || strcmp(argv[4], "exec") != 0) return 76;
    struct stat snapshot;
    if (stat(argv[1] + 13, &snapshot) != 0 || !S_ISREG(snapshot.st_mode) || (snapshot.st_mode & 077) != 0) return 77;
    const char *directory = getenv("OWNED_NATIVE_EVIDENCE");
    if (directory == NULL) return 78;
    char path[4096];
    if (snprintf(path, sizeof(path), "%s/exec-called", directory) >= (int)sizeof(path)) return 79;
    FILE *marker = fopen(path, "a");
    if (marker == NULL) return 80;
    fputs("native exec helper received private snapshot and sanitized loader environment\n", marker);
    if (fclose(marker) != 0) return 81;
    puts("SHELL CHILD START");
    fflush(stdout);
    if (setenv("PS1", "OWNED-SHELL> ", 1) != 0) return 82;
    execl("/bin/sh", "sh", "-i", (char *)NULL);
    return 83;
}
