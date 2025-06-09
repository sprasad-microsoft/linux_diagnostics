import time

class SpaceWatcher:
    def __init__(self, controller):
        self.controller = controller

    def run(self):
        print("SpaceWatcher started running")
        while not self.controller.stop_event.is_set():
            time.sleep(self.controller.config.cleanup["cleanup_interval_sec"])
            print("Performed space cleanup")
