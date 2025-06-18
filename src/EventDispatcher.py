"""
Handles reading events from shared memory, batching them, and dispatching to the controller's event queue.
"""

# import ctypes
import os
import mmap
import time
import struct
import numpy as np

from shared_data import SHM_NAME, SHM_SIZE, SHM_DATA_SIZE, HEAD_TAIL_BYTES, event_dtype, MAX_WAIT

# Ensure that the size of Event and event_dtype is same
# assert ctypes.sizeof(Event) == event_dtype.itemsize, (
#     f"Size mismatch: ctypes Event is {ctypes.sizeof(Event)} bytes, "
#     f"numpy event_dtype is {event_dtype.itemsize} bytes"
# )


class EventDispatcher:
    """
    Polls C ring buffer and drains all events. Parses the raw c struct to Python numpy struct array and sends it to eventQueue.
    """

    def __init__(self, controller):
        """
        Initialize the EventDispatcher.
        """
        self.controller = controller
        self.head_tail_fmt = "<Q" if HEAD_TAIL_BYTES == 8 else "<I"
        self.shm_fd, self.shm_map = self._setup_shared_memory()

    def _setup_shared_memory(self) -> tuple[int, mmap.mmap]:
        """
        Open, create, size, and memory-map the shared memory segment.

        Returns:
            Tuple[int, mmap.mmap]: The file descriptor and mmap object.
        """
        shm_created = False
        shm_file_path = f"/dev/shm{SHM_NAME}"
        try:
            shm_fd = os.open(shm_file_path, os.O_RDWR)
        except FileNotFoundError:
            shm_fd = os.open(shm_file_path, os.O_RDWR | os.O_CREAT, 0o666)
            shm_created = True
        except Exception as e:
            print(f"Failed to open shared memory: {e}")
            raise

        if shm_created:
            try:
                os.ftruncate(shm_fd, SHM_SIZE)
            except Exception as e:
                print(f"Failed to set size of shared memory: {e}")
                os.close(shm_fd)
                raise

        try:
            shm_map = mmap.mmap(
                shm_fd, SHM_SIZE, flags=mmap.MAP_SHARED, prot=mmap.PROT_READ | mmap.PROT_WRITE
            )
        except Exception as e:
            print(f"Failed to map shared memory: {e}")
            os.close(shm_fd)
            raise

        return shm_fd, shm_map

    def _get_buffer_size(self) -> int:
        """Tells how much data is available in the shared memory buffer."""
        self.shm_map.seek(0)
        head = struct.unpack_from(self.head_tail_fmt, self.shm_map, 0)[0]
        tail = struct.unpack_from(self.head_tail_fmt, self.shm_map, HEAD_TAIL_BYTES)[0]
        if tail == head:
            return 0
        if tail < head:
            return head - tail
        # Wrap-around case
        return (SHM_DATA_SIZE - tail) + head

    def run(self) -> None:
        """Loop: poll eventQueue, detect anomalies, and put actions into anomalyActionQueue"""
        print("EventDispatcher started running")
        timer = 3
        while not self.controller.stop_event.is_set():
            no_of_events = self._get_buffer_size() // event_dtype.itemsize
            if no_of_events >= 10 or timer == 0:
                print(
                    f"[Event Dispatcher] {no_of_events} events available, dispatching them"
                )
                timer = 3  # reset timer
                if no_of_events == 0:
                    print("[Event Dispatcher] No events available, waiting for more")
                    continue
                time.sleep(MAX_WAIT)
                raw_events = self._poll_shm_buffer()
                parsed_events = self._parse(raw_events)
                self.controller.eventQueue.put(parsed_events)
            else:
                print(
                    f"[Event Dispatcher] Waiting for more events, {no_of_events} available, "
                    f"sleeping for {timer} seconds"
                )
                time.sleep(1)
                timer -= 1

    def _poll_shm_buffer(self) -> bytes:
        """Fetch a batch of raw events from shared memory."""

        self.shm_map.seek(0)
        head = struct.unpack_from(self.head_tail_fmt, self.shm_map, 0)[0]
        tail = struct.unpack_from(self.head_tail_fmt, self.shm_map, HEAD_TAIL_BYTES)[0]

        if tail == head:
            # no events to read
            return b""

        if tail < head:
            available_bytes = head - tail
            self.shm_map.seek(2 * HEAD_TAIL_BYTES + tail)
            raw = self.shm_map.read(available_bytes)
            tail = (tail + available_bytes) % SHM_DATA_SIZE
            self._update_tail(tail)
            return raw

        # Wrap-around case
        available_bytes = (SHM_DATA_SIZE - tail) + head
        bytes_to_end = SHM_DATA_SIZE - tail
        self.shm_map.seek(2 * HEAD_TAIL_BYTES + tail)
        raw1 = self.shm_map.read(bytes_to_end)
        self.shm_map.seek(2 * HEAD_TAIL_BYTES)
        raw2 = self.shm_map.read(head)
        tail = (tail + available_bytes) % SHM_DATA_SIZE
        self._update_tail(tail)
        return raw1 + raw2

    def _update_tail(self, tail) -> None:
        self.shm_map.seek(HEAD_TAIL_BYTES)
        self.shm_map.write(struct.pack(self.head_tail_fmt, tail))
        self.shm_map.flush()

    def _parse(self, raw: bytes) -> np.ndarray | None:
        """Convert raw struct bytes to a numpy array of events (batch)."""
        if not raw:
            return None
        return np.frombuffer(raw, dtype=event_dtype)

    def cleanup(self) -> None:
        """Clean up resources used by the EventDispatcher."""
        try:
            # Read head and tail before closing mmap
            self.shm_map.seek(0)
            head = struct.unpack_from(self.head_tail_fmt, self.shm_map, 0)[0]
            tail = struct.unpack_from(self.head_tail_fmt, self.shm_map, 8)[0]
            if head != tail:
                print(
                    "EventDispatcher: Warning - head and tail are not equal, indicating potential data loss."
                )

            self.shm_map.close()
            os.close(self.shm_fd)
            os.unlink(f"/dev/shm{SHM_NAME}")
            print("EventDispatcher: Shared memory cleaned up")
        except OSError as e:
            print(f"EventDispatcher: Error cleaning up shared memory: {e}")
