"""Anomaly Watcher Module Monitors events and triggers anomaly detection
handlers."""

import queue
import time
import numpy as np

from shared_data import MAX_WAIT
from utils.anomaly_type import AnomalyType, ANOMALY_TYPE_TO_TOOL_ID
from handlers.latency_anomaly_handler import LatencyAnomalyHandler
from handlers.error_anomaly_handler import ErrorAnomalyHandler
from base.anomaly_handler_base import AnomalyHandler

# Maps enum to anomaly handler classes.
ANOMALY_HANDLER_REGISTRY = {
    AnomalyType.LATENCY: LatencyAnomalyHandler,
    AnomalyType.ERROR: ErrorAnomalyHandler,
    # Add more types here as needed
}


class AnomalyWatcher:
    """Registers its own tail in eventQueue.

    It sleeps for an interval (specified in the config), wakes up and
    drains the queue. It computes the masks to separate events for each
    anomaly type and conducts anomaly analysis. Queues the anomaly
    action type to the anomalyActionQueue.
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
            try:
                anomaly_type_enum = AnomalyType(anomaly_cfg.type.strip().lower())
            except ValueError:
                print(
                    f"[AnomalyWatcher] Warning: Unknown anomaly type '{anomaly_cfg.type}' for '{anomaly_name}'"
                )
                continue

            handler_class = ANOMALY_HANDLER_REGISTRY.get(anomaly_type_enum)
            if handler_class:
                handler_map[anomaly_type_enum] = handler_class(anomaly_cfg)
            else:
                print(
                    f"[AnomalyWatcher] Warning: No handler registered for anomaly type '{anomaly_cfg.type}'"
                )
        return handler_map

    def run(self) -> None:
        """Loop: poll eventQueue, detect anomalies, and put actions into anomalyActionQueue"""
        while not self.controller.stop_event.is_set():
            batch = self.controller.eventQueue.get(True)
            if batch is None:
                self.controller.eventQueue.task_done()
                break  # Exit loop on sentinel

            end_time = time.time() + MAX_WAIT
            while time.time() < end_time:
                try:
                    next_batch = self.controller.eventQueue.get_nowait()
                    if next_batch is None:
                        self.controller.eventQueue.task_done()
                        break  # Exit inner loop immediately on sentinel
                    batch = np.concatenate((batch, next_batch))
                    self.controller.eventQueue.task_done()
                except queue.Empty:
                    break

            for anomaly_type, handler in self.handlers.items():
                tool_id = ANOMALY_TYPE_TO_TOOL_ID[anomaly_type]
                masked_batch = batch[batch["tool"] == tool_id]
                if handler.detect(masked_batch):
                    action = self._generate_action(anomaly_type)
                    self.controller.anomalyActionQueue.put(action)

            self.controller.eventQueue.task_done()
            time.sleep(self.interval)

    def _generate_action(self, anomaly_type: AnomalyType) -> dict:
        """Generate an action based on the detected anomaly."""
        timestamp_ns = int(time.time() * 1e9)  # nanoseconds since epoch
        return {
            "anomaly": anomaly_type,
            "timestamp": timestamp_ns,
        }
