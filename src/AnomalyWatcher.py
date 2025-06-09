from enum import Enum
from abc import ABC, abstractmethod
import queue
import time

from shared_data import *

class AnomalyType(Enum):
    LATENCY = "latency"
    ERROR = "error"
    # Add more types as needed

class AnomalyHandler(ABC):
    def __init__(self, config: AnomalyConfig):
        self.config = config

    @abstractmethod
    def detect(self, arr: np.ndarray) -> bool:
        """Return True if anomaly detected."""
        pass

#works only if ebpf code does filtering as per config file (i.e. ignore excluded cmds)
class LatencyAnomalyHandler(AnomalyHandler):

    def __init__(self, config):
        super().__init__(config)
        #bcos im iterating over an array of size 20, using for loop wont affect the performance
        self.threshold_lookup = np.full(len(ALL_SMB_CMDS) + 1,0,dtype=np.uint64)
        for cmd, threshold in self.config.track.items():
            self.threshold_lookup[ALL_SMB_CMDS[cmd]] = threshold*1000000
            
    #works only if ebpf code does filtering as per config file (i.e. ignore excluded cmds)
    def detect(self, arr: np.ndarray) -> bool:
        
        count = np.sum( (arr["metric_latency_ns"] >= self.threshold_lookup[arr["smbcommand"]]) )
        percentage = count / arr.size
        #print(f"Events:{arr}") #for debugging

        print(f"[AnomalyHandler] Detected {count} latency anomalies for {self.config.tool}")
        return count >= 9

class ErrorAnomalyHandler(AnomalyHandler):
    def detect(self, arr: np.ndarray) -> bool:
        # Placeholder for error detection logic
        return False  # Replace with actual logic

class AnomalyWatcher:
    def __init__(self, controller):
        self.controller = controller
        self.interval = self.controller.config.watch_interval_sec
        self.handlers: dict[AnomalyType, AnomalyHandler] = self._load_anomaly_handlers(controller.config)

    def _load_anomaly_handlers(self, config) -> dict:
        handlers = {}
        for name, anomaly_cfg in config.guardian.anomalies.items():
            if anomaly_cfg.type.lower() == "latency":
                handlers[AnomalyType.LATENCY] = LatencyAnomalyHandler(anomaly_cfg)
            elif anomaly_cfg.type.lower() == "error":
                handlers[AnomalyType.ERROR] = ErrorAnomalyHandler(anomaly_cfg)
        return handlers

    def _get_batch(self):
        """Fetch and combine all available batches from the eventQueue into a single numpy array."""
        combined_batches = np.empty(0, dtype=event_dtype)
        while True:
            try:
                batch = self.controller.eventQueue.get_nowait()
                combined_batches = np.concatenate((combined_batches,batch))
            except queue.Empty:
                break
        return combined_batches

    def run(self) -> None:
        while not self.controller.stop_event.is_set():
            batch = self._get_batch()
            #print each event (reomve this code later)
            if batch.size>0:
                print("[Anomaly Watcher] Batch")
            for event in batch:
                print(f"Event: {event}")
            if batch.size > 0:
                for anomaly_type, handler in self.handlers.items():
                    # this will only filter latency anomalies for now (tool=0)
                    filtered_batch = batch[batch["tool"] == 0]
                    # filtered_batch = batch[np.where(batch["tool"] == 0)]
                    # can do this also, but the method without np.where is faster
                    if handler.detect(filtered_batch):
                        action = self._generate_action(anomaly_type, filtered_batch)
                        self.controller.anomalyActionQueue.put(action)
            time.sleep(self.interval)

    def _generate_action(self, anomaly_type: AnomalyType, batch: np.ndarray) -> dict:
        """Generate an action based on the detected anomaly."""
        timestamp = int(time.time() * 1e9)  # nanoseconds since epoch
        return {
            "anomaly": anomaly_type,
            "timestamp": timestamp,
        }
