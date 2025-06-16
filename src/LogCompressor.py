import queue
import concurrent.futures
import os
import tarfile
import shutil


class LogCompressor:
    def __init__(self, controller):
        self.controller = controller
        self.compression_pool = concurrent.futures.ProcessPoolExecutor(max_workers=2)

    def run(self):
        print("LogCompressor started running")
        while not self.controller.stop_event.is_set():
            try:
                output_subdir = self.controller.archiveQueue.get()
                self.compression_pool.submit(self._compress, output_subdir)
                print(f"[Log Compressor] Compressed logs for directory: {output_subdir}")
                self.controller.archiveQueue.task_done()
            except queue.Empty:
                continue
    
    def _compress(self, output_subdir):
        archive_path = output_subdir.rstrip(os.sep) + ".tar.gz"
        print(f"Compressing logs from {output_subdir} into {archive_path}")
        with tarfile.open(archive_path, "w:gz") as tar:
            tar.add(output_subdir, arcname=os.path.basename(output_subdir))
        print(f"Compressed logs into {archive_path}")
        shutil.rmtree(output_subdir)
