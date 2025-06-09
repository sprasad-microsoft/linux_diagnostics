import queue

class LogCompressor:
    def __init__(self, controller):
        self.controller = controller

    def run(self):
        print("LogCompressor started running")
        while not self.controller.stop_event.is_set():
            try:
                batch_id = self.controller.archiveQueue.get(timeout=1)
                print(f"Compressed logs for batch: {batch_id}")
                self.controller.archiveQueue.task_done()
            except queue.Empty:
                continue
