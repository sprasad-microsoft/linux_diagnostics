"""Anomaly Watcher Module Monitors events and triggers anomaly detection
handlers."""

import logging
import queue
import time
import numpy as np

from shared_data import MAX_WAIT
from utils.anomaly_type import AnomalyType, ANOMALY_TYPE_TO_TOOL_ID
from handlers.latency_anomaly_handler import LatencyAnomalyHandler
from handlers.error_anomaly_handler import ErrorAnomalyHandler
from base.AnomalyHandlerBase import AnomalyHandler

logger = logging.getLogger(__name__)

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
        # Metrics tracking
        if __debug__:
            self.total_count = 0
            self.batch_count = 0
            self.anomaly_counts = {anomaly_type: 0 for anomaly_type in self.handlers.keys()}
            self.start_time = time.time()
            self.events_by_tool = {}  # Track events per tool type
        
        if __debug__:
            logger.info("AnomalyWatcher initialized with %d handlers, interval=%ds", len(self.handlers), self.interval)

    def _load_anomaly_handlers(self, config) -> dict[AnomalyType, AnomalyHandler]:
        handler_map = {}
        for anomaly_name, anomaly_cfg in config.guardian.anomalies.items():
            try:
                anomaly_type_enum = AnomalyType(anomaly_cfg.type.strip().lower())
            except ValueError:
                logger.warning("Unknown anomaly type '%s' for '%s'", anomaly_cfg.type, anomaly_name)
                continue

            handler_class = ANOMALY_HANDLER_REGISTRY.get(anomaly_type_enum)
            if handler_class:
                handler_map[anomaly_type_enum] = handler_class(anomaly_cfg)
                logger.debug("Loaded handler for anomaly type: %s", anomaly_cfg.type)
            else:
                logger.warning("No handler registered for anomaly type '%s'", anomaly_cfg.type)
        return handler_map

    def run(self) -> None:
        """Loop: poll eventQueue, detect anomalies, and put actions into anomalyActionQueue"""
        while True:
            batch = self.controller.eventQueue.get(True)
            if batch is None:
                self.controller.eventQueue.task_done()
                self.controller.anomalyActionQueue.put(None)
                break  # Exit loop on sentinel

            end_time = time.time() + MAX_WAIT
            sentinal_found = False
            while time.time() < end_time:
                try:
                    next_batch = self.controller.eventQueue.get_nowait()
                    if next_batch is None:
                        self.controller.eventQueue.task_done()
                        sentinal_found = True
                        break  # Exit inner loop immediately on sentinel
                    batch = np.concatenate((batch, next_batch))
                    self.controller.eventQueue.task_done()
                except queue.Empty:
                    break

            
            if __debug__:
                self.total_count += len(batch)
                self.batch_count += 1
                logger.debug("Processing batch of %d events, total count: %d", len(batch), self.total_count)

            for anomaly_type, handler in self.handlers.items():
                tool_id = ANOMALY_TYPE_TO_TOOL_ID[anomaly_type]
                masked_batch = batch[batch["tool"] == tool_id]
                
                if __debug__:
                    # Track events per tool type
                    if tool_id not in self.events_by_tool:
                        self.events_by_tool[tool_id] = 0
                    self.events_by_tool[tool_id] += len(masked_batch)
                
                if len(masked_batch) > 0 and handler.detect(masked_batch):
                    action = self._generate_action(anomaly_type)
                    self.controller.anomalyActionQueue.put(action)
                    logger.info("Anomaly detected: %s (%d events analyzed)", anomaly_type.value, len(masked_batch))
                    
                    if __debug__:
                        self.anomaly_counts[anomaly_type] += 1
                        # Log detailed metrics every 10 anomalies
                        if sum(self.anomaly_counts.values()) % 10 == 0:
                            self._log_metrics()

            self.controller.eventQueue.task_done()
            if sentinal_found:
                self.controller.anomalyActionQueue.put(None)
                break
            time.sleep(self.interval)

    def _log_metrics(self) -> None:
        """Log comprehensive metrics for debugging and performance analysis."""
        if __debug__:
            runtime = time.time() - self.start_time
            total_anomalies = sum(self.anomaly_counts.values())
            
            logger.debug("=== AnomalyWatcher Metrics ===")
            logger.debug("Runtime: %.1fs, Batches: %d, Total Events: %d", 
                        runtime, self.batch_count, self.total_count)
            logger.debug("Total Anomalies: %d, Anomaly Rate: %.2f/min", 
                        total_anomalies, (total_anomalies * 60) / runtime if runtime > 0 else 0)
            logger.debug("Events/sec: %.1f, Batches/sec: %.2f", 
                        self.total_count / runtime if runtime > 0 else 0,
                        self.batch_count / runtime if runtime > 0 else 0)
            
            for anomaly_type, count in self.anomaly_counts.items():
                if count > 0:
                    logger.debug("  %s: %d anomalies", anomaly_type.value, count)

    def _generate_action(self, anomaly_type: AnomalyType) -> dict:
        """Generate an action based on the detected anomaly."""
        timestamp_ns = int(time.time() * 1e9)  # nanoseconds since epoch
        return {
            "anomaly": anomaly_type,
            "timestamp": timestamp_ns,
        }
