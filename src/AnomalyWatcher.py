"""
Anomaly Watcher Module
Monitors events and triggers anomaly detection handlers.
"""

import queue
import time
import numpy as np

from shared_data import event_dtype
from models import AnomalyType
from handlers import LatencyAnomalyHandler, ErrorAnomalyHandler
from base import AnomalyHandler

ANOMALY_HANDLER_REGISTRY = {
    AnomalyType.LATENCY: LatencyAnomalyHandler,
    AnomalyType.ERROR: ErrorAnomalyHandler,
    # Add more types here as needed
}


class AnomalyWatcher:
    """
    Registers its own tail in eventQueue. It sleeps for an interval (specified in the config), wakes up and drains the queue.
    It computes the masks to separate events for each anomaly type and conducts anomaly analysis.
    Queues the anomaly action type to the anomalyActionQueue.
    """

    def __init__(self, controller):
        """Initialize the AnomalyWatcher with the controller instance."""
        self.controller = controller
        self.interval = getattr(self.controller.config, "watch_interval_sec", 1)  # 1 second default
        self.handlers: dict[AnomalyType, AnomalyHandler] = self._load_anomaly_handlers(
            controller.config
        )

    def _load_anomaly_handlers(self, config) -> dict[AnomalyType, AnomalyHandler]:
        handler_map = {}
        for anomaly_name, anomaly_cfg in config.guardian.anomalies.items():
            anomaly_type_str = anomaly_cfg.type.lower()
            handler_class = ANOMALY_HANDLER_REGISTRY.get(anomaly_type_str)
            try:
                anomaly_type_enum = AnomalyType(anomaly_type_str)
            except ValueError:
                print(
                    f"[AnomalyWatcher] Warning: Unknown anomaly type '{anomaly_type_str}' for '{anomaly_name}'"
                )
                continue
            if handler_class:
                handler_map[anomaly_type_enum] = handler_class(anomaly_cfg)
            else:
                print(
                    f"[AnomalyWatcher] Warning: No handler registered for anomaly type '{anomaly_type_str}'"
                )
        return handler_map

    def _get_batch(self) -> np.ndarray:
        """Fetch and combine all available batches from the eventQueue into a single numpy array."""
        combined_batches = np.empty(0, dtype=event_dtype)
        while True:
            try:
                batch = self.controller.eventQueue.get_nowait()
                combined_batches = np.concatenate((combined_batches, batch))
            except queue.Empty:
                break
        return combined_batches

    def run(self) -> None:
        """Loop: poll eventQueue, detect anomalies, and put actions into anomalyActionQueue"""
        while not self.controller.stop_event.is_set():
            batch = self._get_batch()

            # print each event (reomve this code later)
            if batch.size > 0:
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
                        action = self._generate_action(anomaly_type)
                        self.controller.anomalyActionQueue.put(action)
            time.sleep(self.interval)

    def _generate_action(self, anomaly_type: AnomalyType) -> dict:
        """Generate an action based on the detected anomaly."""
        timestamp_ns = int(time.time() * 1e9)  # nanoseconds since epoch
        return {
            "anomaly": anomaly_type,
            "timestamp": timestamp_ns,
        }
