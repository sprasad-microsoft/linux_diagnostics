#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include <sys/mman.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <stdint.h>
#include <stdlib.h>
#include <errno.h>

#define SHM_NAME "/bpf_shm"
#define TASK_COMM_LEN 16
#define MAX_ENTRIES 2048
#define PAGE_SIZE 4096
#define SHM_SIZE ((MAX_ENTRIES + 1) * PAGE_SIZE)
#define HEAD_TAIL_BYTES sizeof(uint64_t)
#define SHM_DATA_SIZE ((SHM_SIZE/1000 - 2 * HEAD_TAIL_BYTES)) // match Python

union metrics {
    unsigned long long latency_ns;
    int retval;
};

struct event {
    int32_t pid;
    uint64_t cmd_end_time_ns;
    uint64_t session_id;
    uint64_t mid;
    uint16_t smbcommand;
    union metrics metric;
    uint8_t tool;
    uint8_t is_compounded;
    char task[TASK_COMM_LEN];
};

int main() {
    int created = 0;
    int shm_fd = shm_open(SHM_NAME, O_RDWR, 0666);
    if (shm_fd < 0 && errno == ENOENT) {
        // If shm does not exist, create it
        shm_fd = shm_open(SHM_NAME, O_CREAT | O_RDWR, 0666);
        if (shm_fd < 0) {
            perror("shm_open");
            return 1;
        }
        created = 1;
    }
    if (shm_fd < 0) {
        perror("shm_open");
        return 1;
    }
    if (created) {
        if (ftruncate(shm_fd, SHM_SIZE) < 0) {
            perror("ftruncate");
            close(shm_fd);
            return 1;
        }
    }

    void *shm_base = mmap(NULL, SHM_SIZE, PROT_READ | PROT_WRITE, MAP_SHARED, shm_fd, 0);
    if (shm_base == MAP_FAILED) {
        perror("mmap");
        close(shm_fd);
        return 1;
    }

    // Head and tail pointers
    uint64_t *head = (uint64_t *)((char *)shm_base + 0);
    uint64_t *tail = (uint64_t *)((char *)shm_base + 8);
    char *data = (char *)shm_base + 2 * HEAD_TAIL_BYTES;

    // Only initialize if we created the shm
    if (created) {
        *head = 0;
        *tail = 0;
        printf("Initialized head and tail to 0 (new shared memory)\n");
    } else {
        printf("Existing shared memory: head=%lu, tail=%lu\n", *head, *tail);
    }

    struct event dummy = {
        .pid = 4242,
        .cmd_end_time_ns = 1234567890123456ULL,
        .session_id = 0xDEADBEEFDEADBEEFULL,
        .mid = 0xCAFEBABEULL,
        .smbcommand = 0x0001,
        .metric.retval = -10,
        .tool = 7,
        .is_compounded = 0,
        .task = "DUMMY"
    };

    size_t event_size = sizeof(struct event);

    for (int i = 0; i < 30; i++) {
        uint64_t cur_head = *head;
        uint64_t offset = cur_head % SHM_DATA_SIZE;
        dummy.pid = i;

        if (offset + event_size <= SHM_DATA_SIZE) {
            memcpy(data + offset, &dummy, event_size);
        } else {
            // Split write
            size_t first_part = SHM_DATA_SIZE - offset;
            memcpy(data + offset, &dummy, first_part);
            memcpy(data, ((char*)&dummy) + first_part, event_size - first_part);
        }

        *head = (cur_head + event_size) % SHM_DATA_SIZE;

        printf("Dummy event written to shared memory at offset %lu!\n", offset);
        usleep(10000);
        printf("SHM_DATA_SIZE: %lu, head: %lu, tail: %lu\n", SHM_DATA_SIZE, *head, *tail);
    }

    munmap(shm_base, SHM_SIZE);
    close(shm_fd);
    return 0;
}