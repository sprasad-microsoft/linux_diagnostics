import asyncio
from pathlib import Path
import threading
import queue
import shutil
import os

from handlers.JournalctlQuickAction import JournalctlQuickAction
from handlers.CifsstatsQuickAction import CifsstatsQuickAction
from handlers.DmesgQuickAction import DmesgQuickAction
from handlers.DebugDataQuickAction import DebugDataQuickAction
from handlers.MountsQuickAction import MountsQuickAction
from handlers.SmbinfoQuickAction import SmbinfoQuickAction
from handlers.SysLogsQuickAction import SysLogsQuickAction
from utils.anomaly_type import AnomalyType

class LogCollector:
    def __init__(self, controller):
        self.loop = asyncio.new_event_loop()
        self.max_concurrent_tasks = 4
        self.controller = controller
        self.anomaly_interval = getattr(self.controller.config, "watch_interval_sec", 1)  # 1 second default
        self.aod_output_dir = getattr(self.controller.config, "aod_output_dir", "/var/log/aod")
        self.aod_output_dir = os.path.join(self.aod_output_dir, "batches")
        self.action_factory = {
            "journalctl": lambda: JournalctlQuickAction(self.aod_output_dir, self.anomaly_interval),
            "stats": lambda: CifsstatsQuickAction(self.aod_output_dir),
            "debugdata": lambda: DebugDataQuickAction(self.aod_output_dir),
            "dmesg": lambda: DmesgQuickAction(self.aod_output_dir, self.anomaly_interval),
            "mounts": lambda: MountsQuickAction(self.aod_output_dir),
            "smbinfo": lambda: SmbinfoQuickAction(self.aod_output_dir),
            "syslogs": lambda: SysLogsQuickAction(self.aod_output_dir, num_lines=100),
        }
        self.handlers = self.get_anomaly_events(controller.config)

    def get_anomaly_events(self, config) -> dict:
        """
        Build a mapping from anomaly type to a list of action instances,
        using the 'actions' field from each anomaly config in the loaded config.
        """
        anomaly_events = {}
        for anomaly_name, anomaly_cfg in config.guardian.anomalies.items():
            actions = []
            for action_name in getattr(anomaly_cfg, "actions", []):
                factory = self.action_factory.get(action_name)
                if factory is not None:
                    actions.append(factory())
                else:
                    print(
                        f"[LogCollector] Warning: No factory for action '{action_name}' in anomaly '{anomaly_name}'"
                    )
            try:
                anomaly_type_enum = AnomalyType(anomaly_cfg.type.strip().lower())
                anomaly_events[anomaly_type_enum] = actions
            except ValueError:
                print(
                    f"[LogCollector] Warning: Unknown anomaly type '{anomaly_cfg.type}' for '{anomaly_name}'"
                )
        return anomaly_events

    async def _create_log_collection_task(self, anomaly_event) -> None:
        """ here we wait for the logs to be collected.
        After that, we should compress the logs. In reality, compression would
        be offloaded to the compression worker thread. """
        print(f"Collecting logs for anomaly event {anomaly_event}")
        anomaly_type = anomaly_event["anomaly"]
        batch_id = f"{anomaly_event["timestamp"]}"
        await asyncio.gather(
            *[handler.execute(batch_id) for handler in self.handlers[anomaly_type]]
        )
        output_path = self.handlers[anomaly_type][0].get_output_dir(batch_id)
        shutil.make_archive(output_path, 'zip', output_path)
        shutil.rmtree(output_path)

    async def _create_log_collection_task_with_limit(self, anomaly_event, semaphore: asyncio.Semaphore) -> None:
        # use the with ... statement so that we do not have to manually release the semaphore
        async with semaphore:
            try:
                await self._create_log_collection_task(anomaly_event)
            except Exception as e:
                print(f"Error {e} while collecting logs for anomaly action {anomaly_event}")
            finally:
                # send a task done signal to the queue
                await asyncio.to_thread(self.controller.anomalyActionQueue.task_done)

    async def _run(self):
        currently_running_tasks = set()
        semaphore = asyncio.Semaphore(self.max_concurrent_tasks)

        while True:
            try:
                print("Waiting for anomaly event...")
                anomaly_event = await asyncio.to_thread(self.controller.anomalyActionQueue.get) # we can afford to block here since we send a poison pill when the script stops
                if anomaly_event is None:  # Sentinel to stop the loop
                    self.controller.anomalyActionQueue.task_done()
                    # send sentinal to LogCompressor queue when integrated
                    break
                task = asyncio.create_task(self._create_log_collection_task_with_limit(anomaly_event, semaphore))
                currently_running_tasks.add(task)
                # remove task from the set when done
                task.add_done_callback(currently_running_tasks.discard)
            except Exception as e:
                print(f"Error while processing anomaly event: {e}")
            
        if currently_running_tasks:
            await asyncio.gather(*currently_running_tasks) # wait for all tasks to finish

    def run(self):
        # run forever
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self._run()) # Runner.run() is meant for the main thread, so we use run_until_complete()
        self.loop.close()