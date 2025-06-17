"""
Latency Anomaly Handler
This handler detects latency anomalies based on predefined thresholds for SMB commands.
"""

import numpy as np
from base.anomaly_handler_base import AnomalyHandler
from shared_data import ALL_SMB_CMDS


# works only if ebpf code does filtering as per config file (i.e. ignore excluded cmds)
class LatencyAnomalyHandler(AnomalyHandler):
    """
    Checks if a batch of events has any latency anomalies based on the thresholds defined in the config.
    """

    def __init__(self, latency_config):
        super().__init__(latency_config)
        self.acceptable_percentage = self.config.acceptable_percentage
        # bcos im iterating over an array of size 20, using for loop wont affect the performance
        self.threshold_lookup = np.full(len(ALL_SMB_CMDS) + 1, 0, dtype=np.uint64)
        for smb_cmd, threshold in self.config.track.items():
            self.threshold_lookup[ALL_SMB_CMDS[smb_cmd]] = threshold * 1000000

    # works only if ebpf code does filtering as per config file (i.e. ignore excluded cmds)
    def detect(self, events_batch: np.ndarray) -> bool:

        anomaly_count = np.sum(
            (events_batch["metric_latency_ns"] >= self.threshold_lookup[events_batch["smbcommand"]])
        )
        anomaly_percentage = anomaly_count / events_batch.size
        # print(f"Events:{arr}") #for debugging

        print(f"[AnomalyHandler] Detected {anomaly_count} latency anomalies for {self.config.tool}")
        print(f"{self.acceptable_percentage}")
        return anomaly_count >= 1
        return anomaly_percentage >= self.acceptable_percentage
