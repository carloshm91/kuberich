/* Owned loopback-only native benchmark bridge; never an ambient kubectl. */
#define _POSIX_C_SOURCE 200809L
#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/select.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

#define MAX_CHILDREN 8

static volatile sig_atomic_t stopping = 0;

static void stop_handler(int signum) { (void)signum; stopping = 1; }
static void child_handler(int signum) { (void)signum; }

static int private_config(const char *path) {
    struct stat info;
    if (path[0] != '/' || strlen(path) > 4096 || strstr(path, "/../") != NULL) return -1;
    for (const unsigned char *item = (const unsigned char *)path; *item; item++) {
        if (*item < 32 || *item == 127) return -1;
    }
    char copy[4097], *state = NULL;
    memcpy(copy, path, strlen(path) + 1);
    int parent = open("/", O_RDONLY | O_DIRECTORY | O_NOFOLLOW);
    if (parent < 0) return -1;
    char *part = strtok_r(copy + 1, "/", &state);
    int descriptor = -1;
    while (part != NULL) {
        char *next = strtok_r(NULL, "/", &state);
        if (strcmp(part, ".") == 0 || strcmp(part, "..") == 0) break;
        int child = openat(parent, part, O_RDONLY | O_NOFOLLOW | O_NONBLOCK |
                           (next == NULL ? 0 : O_DIRECTORY));
        if (child < 0) break;
        if (next == NULL) { descriptor = child; break; }
        close(parent);
        parent = child;
        part = next;
    }
    close(parent);
    if (descriptor < 0) return -1;
    int valid = fstat(descriptor, &info) == 0 && S_ISREG(info.st_mode) &&
        info.st_uid == geteuid() && info.st_nlink == 1 && (info.st_mode & 0777) == 0600;
    close(descriptor);
    return valid ? 0 : -1;
}

static void quoted(FILE *stream, const char *value) {
    fputc('"', stream);
    for (const unsigned char *item = (const unsigned char *)value; *item; item++) {
        if (*item == '"' || *item == '\\') fputc('\\', stream);
        if (*item < 32) fprintf(stream, "\\u%04x", *item);
        else fputc(*item, stream);
    }
    fputc('"', stream);
}

static int publish_record(unsigned int port, const char *config) {
    struct stat root, existing;
    if (stat(".", &root) != 0 || root.st_uid != geteuid() || (root.st_mode & 0022)) return -1;
    if (lstat("benchmark-forward.json", &existing) == 0) {
        if (!S_ISREG(existing.st_mode) || existing.st_uid != geteuid() ||
            existing.st_nlink != 1 || (existing.st_mode & 0777) != 0600) return -1;
    } else if (errno != ENOENT) return -1;
    char stage[80];
    if (snprintf(stage, sizeof(stage), ".benchmark-forward.%ld.json", (long)getpid()) >= (int)sizeof(stage)) return -1;
    int descriptor = open(stage, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW, 0600);
    if (descriptor < 0) return -1;
    FILE *output = fdopen(descriptor, "w");
    if (output == NULL) { close(descriptor); unlink(stage); return -1; }
    fprintf(output, "{\"pid\":%ld,\"port\":%u,\"config\":", (long)getpid(), port);
    quoted(output, config);
    fputs("}\n", output);
    int valid = fflush(output) == 0 && fsync(descriptor) == 0 && fchmod(descriptor, 0600) == 0;
    if (fclose(output) != 0) valid = 0;
    if (!valid || rename(stage, "benchmark-forward.json") != 0) { unlink(stage); return -1; }
    return 0;
}

static int send_all(int descriptor, const unsigned char *data, size_t size) {
    while (size) {
        ssize_t written = send(descriptor, data, size, 0);
        if (written <= 0) return -1;
        data += written;
        size -= (size_t)written;
    }
    return 0;
}

static void bridge(int peer, unsigned short upstream_port) {
    int upstream = socket(AF_INET, SOCK_STREAM, 0);
    if (upstream < 0) _exit(81);
    struct sockaddr_in address;
    memset(&address, 0, sizeof(address));
    address.sin_family = AF_INET;
    address.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    address.sin_port = htons(upstream_port);
    if (connect(upstream, (struct sockaddr *)&address, sizeof(address)) != 0 ||
        peer >= FD_SETSIZE || upstream >= FD_SETSIZE) _exit(82);
    int descriptors[2] = {peer, upstream}, active[2] = {1, 1};
    unsigned char buffer[65536];
    while (active[0] || active[1]) {
        fd_set reads;
        FD_ZERO(&reads);
        for (int index = 0; index < 2; index++) if (active[index]) FD_SET(descriptors[index], &reads);
        struct timeval deadline = {3, 0};
        int highest = peer > upstream ? peer : upstream;
        int ready = select(highest + 1, &reads, NULL, NULL, &deadline);
        if (ready <= 0) break;
        for (int index = 0; index < 2; index++) {
            if (!active[index] || !FD_ISSET(descriptors[index], &reads)) continue;
            ssize_t received = recv(descriptors[index], buffer, sizeof(buffer), 0);
            if (received < 0) _exit(83);
            if (received == 0) {
                active[index] = 0;
                shutdown(descriptors[1 - index], SHUT_WR);
            } else if (send_all(descriptors[1 - index], buffer, (size_t)received) != 0) _exit(84);
        }
    }
    close(upstream);
    close(peer);
    _exit(0);
}

static void forget(pid_t *children, int *count, pid_t finished) {
    for (int index = 0; index < *count; index++) {
        if (children[index] == finished) { children[index] = children[--(*count)]; return; }
    }
}

int main(int argc, char **argv) {
    if (argc != 9 || strncmp(argv[1], "--kubeconfig=", 13) != 0 ||
        strcmp(argv[2], "--context=kuberich-test-one") != 0 ||
        strcmp(argv[3], "--namespace=team") != 0 || strcmp(argv[4], "port-forward") != 0 ||
        strcmp(argv[5], "--address=127.0.0.1") != 0 ||
        strcmp(argv[6], "--pod-running-timeout=10s") != 0 ||
        strcmp(argv[7], "pod/backend") != 0 || strcmp(argv[8], "0:8080") != 0) return 71;
    if (private_config(argv[1] + 13) != 0) return 72;
    const char *source_port = getenv("OWNED_BENCHMARK_PORT");
    if (source_port == NULL || *source_port == '\0') return 73;
    for (const char *item = source_port; *item; item++) if (*item < '0' || *item > '9') return 73;
    char *tail = NULL;
    errno = 0;
    long number = strtol(source_port, &tail, 10);
    if (errno || *tail || number < 1 || number > 65535) return 73;
    struct sigaction action;
    memset(&action, 0, sizeof(action));
    sigemptyset(&action.sa_mask);
    action.sa_handler = stop_handler;
    if (sigaction(SIGTERM, &action, NULL) || sigaction(SIGINT, &action, NULL)) return 74;
    action.sa_handler = child_handler;
    if (sigaction(SIGCHLD, &action, NULL)) return 74;
    signal(SIGPIPE, SIG_IGN);
    int listener = socket(AF_INET, SOCK_STREAM, 0);
    if (listener < 0 || listener >= FD_SETSIZE) return 75;
    struct sockaddr_in address;
    memset(&address, 0, sizeof(address));
    address.sin_family = AF_INET;
    address.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    address.sin_port = 0;
    if (bind(listener, (struct sockaddr *)&address, sizeof(address)) || listen(listener, MAX_CHILDREN)) return 75;
    socklen_t length = sizeof(address);
    if (getsockname(listener, (struct sockaddr *)&address, &length)) return 75;
    unsigned int port = ntohs(address.sin_port);
    if (publish_record(port, argv[1] + 13) != 0) return 76;
    printf("Forwarding from 127.0.0.1:%u -> 8080\n", port);
    if (fflush(stdout)) return 77;
    pid_t children[MAX_CHILDREN];
    int count = 0, result = 0;
    while (!stopping) {
        pid_t finished;
        while ((finished = waitpid(-1, NULL, WNOHANG)) > 0) forget(children, &count, finished);
        if (count == MAX_CHILDREN) {
            finished = waitpid(-1, NULL, 0);
            if (finished > 0) forget(children, &count, finished);
            continue;
        }
        fd_set reads;
        FD_ZERO(&reads);
        FD_SET(listener, &reads);
        struct timeval deadline = {1, 0};
        int ready = select(listener + 1, &reads, NULL, NULL, &deadline);
        if (ready < 0 && errno == EINTR) continue;
        if (ready < 0) { result = 78; break; }
        if (!ready) continue;
        int peer = accept(listener, NULL, NULL);
        if (peer < 0 && errno == EINTR) continue;
        if (peer < 0) { result = 78; break; }
        sigset_t blocked, previous;
        sigemptyset(&blocked);
        sigaddset(&blocked, SIGTERM);
        sigaddset(&blocked, SIGINT);
        if (sigprocmask(SIG_BLOCK, &blocked, &previous) != 0) { close(peer); result = 79; break; }
        pid_t child = fork();
        if (child == 0) {
            signal(SIGTERM, SIG_DFL);
            signal(SIGINT, SIG_DFL);
            sigprocmask(SIG_SETMASK, &previous, NULL);
            close(listener);
            bridge(peer, (unsigned short)number);
        }
        close(peer);
        if (child >= 0) children[count++] = child;
        sigprocmask(SIG_SETMASK, &previous, NULL);
        if (child < 0) { result = 79; break; }
    }
    close(listener);
    for (int index = 0; index < count; index++) kill(children[index], SIGTERM);
    while (waitpid(-1, NULL, 0) > 0 || errno == EINTR) {}
    return result;
}
