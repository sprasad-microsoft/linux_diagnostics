import queue

class AuditLogger:
    def __init__(self, controller):
        self.controller = controller

    def run(self):
        print("AuditLogger started running")
        while not self.controller.stop_event.is_set():
            try:
                record = self.controller.auditQueue.get(timeout=1)
                print(f"Logged audit record: {record}")
                self.controller.auditQueue.task_done()
            except queue.Empty:
                continue
