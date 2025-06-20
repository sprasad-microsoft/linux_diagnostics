''' The aim of this code is to demonstrate how asyncio can be used to collect
logs from multiple sources and commands concurrently. '''

import asyncio
from pathlib import Path
import threading
import queue
import shutil

async def collect_proc_fs_output(in_path: Path, out_path: Path) -> None:
    in_path = Path(in_path)
    out_path = Path(out_path)
    print(f"Collecting proc fs output from: {in_path}")
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        print(f"Error creating directory {out_path.parent}: {e}")
        return
    await asyncio.sleep(1)
    data = Path(in_path).read_bytes()
    out_path.write_bytes(data)
    print(f"Output written to: {out_path}")

async def collect_cmd_output(cmd: str, out_path: Path) -> None:
    out_path = Path(out_path)
    print(f"Collecting command output for: {cmd}")
    proc = await asyncio.create_subprocess_exec(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL
    )
    stdout, _ = await proc.communicate()
    if stdout:
        out_path.write_bytes(stdout)
    print(f"Command output written to: {out_path}")




class CollectLogs:
    def __init__(self, anomaly_queue: queue.Queue):
        self.loop = asyncio.new_event_loop()
        self.max_concurrent_tasks = 4
        self.anomaly_queue = anomaly_queue
        self.handlers = [
            lambda: collect_proc_fs_output(Path("/proc/fs/cifs/DebugData"), Path("./all/out/cifs_debug_data.txt")),
            lambda: collect_proc_fs_output("/proc/net/dev", "./all/out/net_data.txt"),
            lambda: collect_cmd_output("dmesg", "./all/out/dmesg_output.txt"),
        ]

    async def compress_logs(self, in_path: Path, out_path: Path) -> None:
        """ Compress the logs into a zip file. """
        proc = await asyncio.create_subprocess_exec(
            "zip", "-r", str(out_path), str(in_path),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            print(f"Error compressing logs: {stderr.decode().strip()}")

    async def _create_log_collection_task(self, anomaly_event: int) -> None:
        """ here we wait for the logs to be collected.
        After that, we should compress the logs. In reality, compression would
        be offloaded to the compression worker thread. """
        if (anomaly_event < 15):
            print(f"Collecting logs for anomaly event {anomaly_event}")
            await asyncio.gather(
                *[handler() for handler in self.handlers]
            )
            # after this, compress the logs. In reality we would send a signal to the compression worker thread
            # await asyncio.to_thread(self.compression_queue.put_nowait(event))
            # await asyncio.to_thread(shutil.make_archive, "compressed_logs", 'zip', 'all/out') 
            shutil.make_archive("compressed_logs", 'zip', 'all/out')
            # await self.compress_logs(Path("./all/out"), Path(f"./compressed_logs{anomaly_event}.zip")) # fastest

    async def _create_log_collection_task_with_limit(self, anomaly_event: int, semaphore: asyncio.Semaphore) -> None:
        # use the with ... statement so that we do not have to manually release the semaphore
        async with semaphore:
            try:
                await self._create_log_collection_task(anomaly_event)
            except Exception as e:
                print(f"Error {e} while collecting logs for anomaly event {anomaly_event}")
            finally:
                # send a task done signal to the queue
                await asyncio.to_thread(self.anomaly_queue.task_done)

    async def _run(self):
        currently_running_tasks = set()
        semaphore = asyncio.Semaphore(self.max_concurrent_tasks)

        while True:
            try:
                print("Waiting for anomaly event...")
                anomaly_event = await asyncio.to_thread(self.anomaly_queue.get) # we can afford to block here since we send a poison pill when the script stops
                if anomaly_event is None:  # Sentinel to stop the loop
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
    

anomaly_queue = queue.Queue()
collector = CollectLogs(anomaly_queue)


# spawn two rheads to simulate the anomaly events
def anomaly_event_generator(queue: queue.Queue):
    for i in range(20):
        queue.put(i)
        if i > 10:
            queue.put(None)
    queue.put(None)

anomaly_thread = threading.Thread(target=anomaly_event_generator, args=(anomaly_queue,))
collector_thread = threading.Thread(target=collector.run)
anomaly_thread.start()
collector_thread.start()

anomaly_thread.join()  # Wait for the anomaly event generator to finish
collector_thread.join()  # Wait for the collector to finish