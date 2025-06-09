import ctypes
import os
import mmap
import numpy as np
import time
import struct

from shared_data import *

#ensure that the size of Event and event_dtype is same
assert ctypes.sizeof(Event) == event_dtype.itemsize, (
    f"Size mismatch: ctypes Event is {ctypes.sizeof(Event)} bytes, "
    f"numpy event_dtype is {event_dtype.itemsize} bytes"
)

class EventDispatcher:

    def __init__(self, controller):
        self.controller = controller
        created = False
        shm_path = f"/dev/shm{SHM_NAME}"
        try:
            self.fd = os.open(shm_path, os.O_RDWR)
        except FileNotFoundError:
            # Try to create if not found
            self.fd = os.open(shm_path, os.O_RDWR | os.O_CREAT, 0o666)
            created = True
        except Exception as e:
            print(f"Failed to open shared memory: {e}")
            raise

        if created:
            try:
                os.ftruncate(self.fd, SHM_SIZE)
            except Exception as e:
                print(f"Failed to set size of shared memory: {e}")
                os.close(self.fd)
                raise

        try:
            self.m = mmap.mmap(self.fd, SHM_SIZE, flags=mmap.MAP_SHARED, prot=mmap.PROT_READ | mmap.PROT_WRITE)
        except Exception as e:
            print(f"Failed to map shared memory: {e}")
            os.close(self.fd)
            raise

    def run(self):
        print("EventDispatcher started running")
        while not self.controller.stop_event.is_set():
            raw_events = self._poll_shm_buffer()
            batch = self._parse(raw_events)
            if batch is not None and len(batch) > 0:
                self.controller.eventQueue.put(batch)
                print("[Event Dispatcher] Batch put")
            time.sleep(1)  # Adjust as needed

        # After stop_event is set, do a final drain
        raw_events = self._poll_shm_buffer()
        batch = self._parse(raw_events)
        if batch is not None and len(batch) > 0:
            self.controller.eventQueue.put(batch)
        print("EventDispatcher: Final drain complete, exiting.")

    def _poll_shm_buffer(self) -> bytes:
        """Fetch a batch of raw events from shared memory."""
        fmt = "<Q" if HEAD_TAIL_BYTES == 8 else "<I"
        self.m.seek(0)
        head = struct.unpack_from(fmt, self.m, 0)[0]
        tail = struct.unpack_from(fmt, self.m, HEAD_TAIL_BYTES)[0]
        event_size = ctypes.sizeof(Event)
        events = []

        if tail == head:
            return b''

        if tail < head:
            available = head - tail
            count = available // event_size
            offset = tail % SHM_DATA_SIZE
            self.m.seek(2 * HEAD_TAIL_BYTES + offset)
            raw = self.m.read(count * event_size)
            tail = (tail + count * event_size) % SHM_DATA_SIZE
            self._update_tail(tail)
            return raw
        else:
            # Wrap-around case
            available = (SHM_DATA_SIZE - tail) + head
            offset = tail % SHM_DATA_SIZE
            bytes_to_end = SHM_DATA_SIZE - offset
            self.m.seek(2 * HEAD_TAIL_BYTES + offset)
            raw1 = self.m.read(bytes_to_end)
            self.m.seek(2 * HEAD_TAIL_BYTES)
            raw2 = self.m.read(head)
            tail = (tail + available) % SHM_DATA_SIZE
            self._update_tail(tail)
            return raw1 + raw2

    def _update_tail(self, tail):
        self.m.seek(8)
        self.m.write(struct.pack("<Q", tail))
        self.m.flush()

    def _parse(self, raw: bytes):
        """Convert raw struct bytes to a numpy array of events (batch)."""
        if not raw:
            return None
        return np.frombuffer(raw, dtype=event_dtype)

    def cleanup(self):
        try:
            # Read head and tail before closing mmap
            self.m.seek(0)
            head = struct.unpack_from("<Q", self.m, 0)[0]
            tail = struct.unpack_from("<Q", self.m, 8)[0]
            if head != tail:
                print("EventDispatcher: Warning - head and tail are not equal, indicating potential data loss.")

            self.m.close()
            os.close(self.fd)
            os.unlink(f"/dev/shm{SHM_NAME}")
            print("EventDispatcher: Shared memory cleaned up")
        except OSError as e:
            print(f"EventDispatcher: Error cleaning up shared memory: {e}")
