import queue

class LogCollectorManager:
    def __init__(self, controller):
        self.controller = controller

    def run(self):
        print("LogCollectorManager started running")
        while not self.controller.stop_event.is_set():
            try:
                action = self.controller.anomalyActionQueue.get(timeout=1)
                print(f"Collected logs for action: {action}")
                self.controller.anomalyActionQueue.task_done()
            except queue.Empty:
                continue
