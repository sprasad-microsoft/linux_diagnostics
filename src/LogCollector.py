"""When an anomaly is detected, this manager collects logs (runs quick actions)"""

import os
import queue
import time
import concurrent.futures

from handlers.JournalctlQuickAction import JournalctlQuickAction
from handlers.CifsstatsQuickAction import CifsstatsQuickAction
from handlers.DmesgQuickAction import DmesgQuickAction
from handlers.DebugDataQuickAction import DebugDataQuickAction
from handlers.MountsQuickAction import MountsQuickAction
from handlers.SmbinfoQuickAction import SmbinfoQuickAction
from handlers.SysLogsQuickAction import SysLogsQuickAction

class LogCollector:
    """It consumes the anomalyActionQueue. 
    For each anomaly event, it submits the quick log collection actions “QuickActions” to a bounded threadpool"""

    def __init__(self, controller):
        self.controller = controller
        self.aod_output_dir = getattr(self.controller.config, "aod_output_dir", "/var/log/aod")
        self.batches_root = os.path.join(self.aod_output_dir, "batches")
        self.anomaly_interval = getattr(self.controller.config, "watch_interval_sec", 1)
        self.quick_actions_pool = concurrent.futures.ThreadPoolExecutor(max_workers=4)
        self.params = {"batches_root": self.batches_root, "anomaly_interval": self.anomaly_interval}
        self.action_factory = {
            "journalctl": lambda: JournalctlQuickAction(self.params),
            "stats": lambda: CifsstatsQuickAction(self.params),
            "dmesg": lambda: DmesgQuickAction(self.params),
            "debugdata": lambda: DebugDataQuickAction(self.params),
            "mounts": lambda: MountsQuickAction(self.params),
            "smbinfo": lambda: SmbinfoQuickAction(self.params),
            "syslogs": lambda: SysLogsQuickAction(self.params),
        }
        self.anomaly_actions = self.set_anomaly_actions()

    def set_anomaly_actions(self) -> dict:
        """
        Build a mapping from anomaly type to a list of action instances,
        using the 'actions' field from each anomaly config in the loaded config.
        """
        anomaly_actions = {}
        for anomaly_name, anomaly_cfg in self.controller.config.guardian.anomalies.items():
            actions = []
            for action_name in anomaly_cfg.actions:
                factory = self.action_factory.get(action_name)
                if factory is not None:
                    actions.append(factory())
                else:
                    print(f"[LogCollectionManager] Warning: No factory for action '{action_name}' in anomaly '{anomaly_name}'")
            anomaly_actions[anomaly_name] = actions
        return anomaly_actions

    def _ensure_batch_dir(self, evt) -> str:
        batch_id = str(evt.get("batch_id", evt.get("timestamp", int(time.time()))))
        batch_dir = os.path.join(self.batches_root, f"aod_{batch_id}")
        os.makedirs(batch_dir, exist_ok=True)
        print(f"[Log Collector][manager] Ensured batch directory exists: {batch_dir}")
        return batch_id

    def _log_to_syslog(self, evt: dict) -> None:
        print(f"[Log Collector][manager] Logging anomaly to syslog: {evt}")

    def run(self) -> None:
        print("[Log Collector][manager] LogCollectorManager started running")
        while not self.controller.stop_event.is_set():
            try:
                evt = self.controller.anomalyActionQueue.get()
                if evt is None:
                    self.controller.anomalyActionQueue.task_done()
                    #self.controller.archiveQueue.put(None)  # Signal to archive queue to stop
                    break
            except queue.Empty:
                continue
            batch_id = self._ensure_batch_dir(evt)
            self._log_to_syslog(evt)
            anomaly_type = (
                evt["anomaly"].name.lower()
                if hasattr(evt.get("anomaly"), "name")
                else str(evt.get("anomaly", "")).lower()
            )

            any_quick_action = False
            quick_actions = []

            print(
                f"[Log Collector][manager] Handling anomaly type '{anomaly_type}' for batch {batch_id}"
            )
            for action in self.anomaly_actions.get(anomaly_type, []):
                # FOR NOW CODE ONLY HANDLES QUICK ACTIONS
                # if isinstance(action, ToolManager):
                #     print(
                #         f"[Log Collector][manager] Extending tool manager for {action.output_subdir} batch {batch_id}"
                #     )
                #     action.extend(batch_id)
                # else:
                if not any_quick_action:
                    # create the in progress marker
                    quick_dir = os.path.join(self.batches_root, f"aod_{batch_id}", "quick")
                    os.makedirs(quick_dir, exist_ok=True)
                    in_progress = os.path.join(quick_dir, ".IN_PROGRESS")
                    open(in_progress, "w", encoding="utf-8").close()
                    any_quick_action = True
                    quick_actions = []
                    print(
                        f"[Log Collector][manager] Submitting quick action {action.__class__.__name__} for batch {batch_id}"
                    )
                quick_actions.append(self.quick_actions_pool.submit(action.execute, batch_id))
            if any_quick_action:
                concurrent.futures.wait(quick_actions, return_when=concurrent.futures.ALL_COMPLETED)
                completed = os.path.join(self.batches_root, f"aod_{batch_id}", "quick", ".COMPLETE")
                if os.path.exists(in_progress):
                    os.rename(in_progress, completed)
                    print(f"[Log Collector][manager] Renamed {in_progress} to {completed}")
                print(
                    f"[Log Collector][manager] Adding quick actions for batch {batch_id} to archive queue"
                )
                quick_output_dir = os.path.join(self.batches_root, f"aod_{batch_id}", "quick")
                any_quick_action = False
                quick_actions = []
            self.controller.anomalyActionQueue.task_done()

    def stop(self) -> None:
        print("[Log Collector][manager] Stopping LogCollectorManager and all tool managers")
        self.quick_actions_pool.shutdown(wait=True)
