#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include <sys/mman.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <stdint.h>
#include <stdlib.h>
#include <errno.h>
#include <time.h>

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

#define CMD_LATENCY_MAP_SIZE 32
struct cmd_latency_key {
    int cmd;
    uint64_t latency;
};
struct cmd_latency_count {
    struct cmd_latency_key key;
    int count;
};
struct cmd_latency_count cmd_latency_map[CMD_LATENCY_MAP_SIZE] = {0};

// Helper to increment (cmd,latency) count
void increment_cmd_latency(int cmd, uint64_t latency) {
    for (int i = 0; i < CMD_LATENCY_MAP_SIZE; ++i) {
        if (cmd_latency_map[i].count == 0) {
            cmd_latency_map[i].key.cmd = cmd;
            cmd_latency_map[i].key.latency = latency;
            cmd_latency_map[i].count = 1;
            return;
        } else if (cmd_latency_map[i].key.cmd == cmd && cmd_latency_map[i].key.latency == latency) {
            cmd_latency_map[i].count += 1;
            return;
        }
    }
}


int main() {
    srand(time(NULL));
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
        .metric.latency_ns = 10,
        .tool = 7,
        .is_compounded = 0,
        .task = "DUMMY"
    };

    size_t event_size = sizeof(struct event);

    

    for (int i = 0; i < 30; i++) {
        uint64_t cur_head = *head;
        uint64_t offset = cur_head % SHM_DATA_SIZE;
        dummy.pid = i;
        
        // Randomly choosing command type and threshold suitable for testing
        int random_choice = rand() % 3 + 1;
        if (random_choice == 1) {
            dummy.metric.latency_ns = (rand() % 2 == 0) ? 7 : 9; // smb read
            dummy.smbcommand = 8;
        } else if (random_choice == 2) {
            dummy.metric.latency_ns = 100; // smb write
            dummy.smbcommand = 9;
        } else {
            dummy.metric.latency_ns = (rand() % 2 == 0) ? 9 : 11; // smb lock
            dummy.smbcommand = 10;
        }
        dummy.metric.latency_ns *= 1e6; // Convert to nanoseconds
        printf("Writing event with pid=%d, smb=%lu, latency_ns=%llu\n",
               dummy.pid, dummy.smbcommand, (unsigned long long)dummy.metric.latency_ns);

        increment_cmd_latency(dummy.smbcommand, dummy.metric.latency_ns);

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

    // Print the (cmd, latency) -> count map after the loop
    for (int i = 0; i < CMD_LATENCY_MAP_SIZE; ++i) {
        if (cmd_latency_map[i].count > 0) {
            printf("(%d, %llu) -> %d\n", cmd_latency_map[i].key.cmd,
                   (unsigned long long)cmd_latency_map[i].key.latency,
                   cmd_latency_map[i].count);
        }
    }
    // print no.of commands with cmd=10 latency=9
    int count_10_11 = 0;
    int count_8_9 = 0;
    for (int i = 0; i < CMD_LATENCY_MAP_SIZE; ++i) {
        if (cmd_latency_map[i].key.cmd == 10 &&
            cmd_latency_map[i].key.latency == 11*1e6 &&
            cmd_latency_map[i].count > 0) {
            count_10_11 = cmd_latency_map[i].count;
        }
        if (cmd_latency_map[i].key.cmd == 8 &&
            cmd_latency_map[i].key.latency == 9*1e6 &&
            cmd_latency_map[i].count > 0) {
            count_8_9 = cmd_latency_map[i].count;
        }
    }
    printf("extra_cnt=%d\n", count_10_11 + count_8_9);

    munmap(shm_base, SHM_SIZE);
    close(shm_fd);
    return 0;
}