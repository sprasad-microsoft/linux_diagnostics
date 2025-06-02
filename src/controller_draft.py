import argparse
import yaml
import os
import warnings
import subprocess
#import psutil
from abc import ABC, abstractmethod

# Define all SMB commands with their corresponding indices
from types import MappingProxyType
ALL_SMB_CMDS = MappingProxyType({
    "SMB2_NEGOTIATE": 0,
    "SMB2_SESSION_SETUP": 1,
    "SMB2_LOGOFF": 2,
    "SMB2_TREE_CONNECT": 3,
    "SMB2_TREE_DISCONNECT": 4,
    "SMB2_CREATE": 5,
    "SMB2_CLOSE": 6,
    "SMB2_FLUSH": 7,
    "SMB2_READ": 8,
    "SMB2_WRITE": 9,
    "SMB2_LOCK": 10,
    "SMB2_IOCTL": 11,
    "SMB2_CANCEL": 12,
    "SMB2_ECHO": 13,
    "SMB2_QUERY_DIRECTORY": 14,
    "SMB2_CHANGE_NOTIFY": 15,
    "SMB2_QUERY_INFO": 16,
    "SMB2_SET_INFO": 17,
    "SMB2_OPLOCK_BREAK": 18,
    "SMB2_SERVER_TO_CLIENT_NOTIFICATION": 19
})

# AODController
class AODController:
    def __init__(self, mode, config_path, continuous=False):
        self.mode = mode
        self.config_path = config_path
        self.continuous = continuous
        self.config = None
        self.strategy = None

    def load_config(self):
        self.config = ConfigParser(self.config_path).parse()

    def select_strategy(self):
        if self.mode == "Guardian":
            self.strategy = GuardianMode(self.config)
        elif self.mode == "Watcher":
            self.strategy = WatcherMode(self.config)
        else:
            raise ValueError("Unsupported mode")

    def run(self):
        self.load_config()
        if not self.config:
            raise ValueError("Configuration not loaded. Please check the config path.")
        self.select_strategy()
        self.strategy.execute()

# Config Parser
class ConfigParser:
    def __init__(self, path):
        self.path = path

    def parse(self):
        with open(self.path, 'r') as f:
            return yaml.safe_load(f)

# Strategy Pattern
class RunModeStrategy(ABC):
    def __init__(self, config):
        self.config = config

    @abstractmethod
    def execute(self):
        pass

class GuardianMode(RunModeStrategy):

    def __init__(self, config):
        self.config = config.get("Guardian", {})
        self.timer = self.config.get("Timer")  # Ask for the default timer value and add it later

    def execute(self):
        print("Running in Guardian mode")
        anomalies = self.config.get("Anomalies", {})
        if not anomalies:
            raise ValueError("No anomalies configured in the YAML file.")
        for anomaly_type, section in anomalies.items():
            print(f"Processing anomaly type: {anomaly_type}")
            parser = AnomalyParserFactory.get_parser(anomaly_type, section)
            parsed_config = parser.parse()
            # ebpf launcher wont need all info in config
            # should i only give what the ebpf launcher needs?
            # this is encapsulation or smth right 
            ebpf_launcher = EBPFLauncherFactory.get_launcher(anomaly_type, parsed_config)
            ebpf_launcher.launch()
        #will handle ebpf launching and event dispatcher launching part later

class WatcherMode(RunModeStrategy):
    def execute(self):
        print("Running in Watcher mode (not implemented yet)")

# Anomaly Parser Factory
class AnomalyParserFactory:
    @staticmethod
    def get_parser(anomaly_type, config_section):
        if anomaly_type == "Latency":
            return LatencyConfigParser(config_section)
        elif anomaly_type == "Error":
            return ErrorConfigParser(config_section)
        else:
            raise ValueError(f"Unsupported anomaly type: {anomaly_type}")

# Anomaly Config Parsers
class AnomalyConfigParser:
    def __init__(self, config):
        self.config = config

    @abstractmethod
    def parse(self):
        pass

class LatencyConfigParser(AnomalyConfigParser):

    def __init__(self, config):
        super().__init__(config)
        self.default_threshold = None
        self.latency_mode = None
        self.command_map = {
         "SMB2_NEGOTIATE": -1,
         "SMB2_SESSION_SETUP": -1,
         "SMB2_LOGOFF": -1,
         "SMB2_TREE_CONNECT": -1,
         "SMB2_TREE_DISCONNECT": -1,
         "SMB2_CREATE": -1,
         "SMB2_CLOSE": -1,
         "SMB2_FLUSH": -1,
         "SMB2_READ": -1,
         "SMB2_WRITE": -1,
         "SMB2_LOCK": -1,
         "SMB2_IOCTL": -1,
         "SMB2_CANCEL": -1,
         "SMB2_ECHO": -1,
         "SMB2_QUERY_DIRECTORY": -1,
         "SMB2_CHANGE_NOTIFY": -1,
         "SMB2_QUERY_INFO": -1,
         "SMB2_SET_INFO": -1,
         "SMB2_OPLOCK_BREAK": -1,
         "SMB2_SERVER_TO_CLIENT_NOTIFICATION": -1
        }

    def parse(self):
      try:  
        #extract default threshold and latency mode from config
        self.default_threshold = self.config.get("DefaultThreshold")
        self.latency_mode = self.config.get("Mode")

        track_commands = self.config.get("TrackCommands", [])
        exclude_commands = self.config.get("ExcludeCommands", [])

        # Validate latency mode constraints
        if self.latency_mode == "trackonly" and exclude_commands:
            warnings.warn("Exclude commands will be ignored in trackonly mode.")
            exclude_commands = []
        elif self.latency_mode == "excludeonly" and track_commands:
            warnings.warn("Track commands will be ignored in excludeonly mode.")
            track_commands = []
        
        # Validate and filter commands
        self.validate_smb_commands(track_commands, exclude_commands)
        
        # Change all command's threshold to default threshold in the command map
        for command in self.command_map:
            self.command_map[command] = self.default_threshold

        # Apply latency mode operations
        if self.latency_mode == "all":
            self.track_modif(track_commands)    #so that we dont raise error if track_command is also an exclude_command, im doing track_modif first
            self.exclude_some(exclude_commands)
            print("oof")
        elif self.latency_mode == "trackonly":
            self.create_new_track(track_commands)
        elif self.latency_mode == "excludeonly":
            self.exclude_some(exclude_commands)
        else:
            raise ValueError("Invalid latency mode. Must be 'all', 'trackonly', or 'excludeonly'.")

        # return tool, acceptable percentage, default threshold, and command map
        self.acceptable_percentage = self.config.get("AcceptablePercentage")
        self.tool = self.config.get("Tool")
        self.actions = self.config.get("Actions", {})

        #only for degugging purposes
        print(f"Tool: {self.tool}, Acceptable Percentage: {self.acceptable_percentage}, Default Threshold: {self.default_threshold}")
        #print command map in table format
        print("Command Map:")
        print("{:<30} {:<10}".format("Command", "Threshold"))
        for command, threshold in self.command_map.items():
            print("{:<30} {:<10}".format(command, threshold))

        #can u help me improve the return statement, i want to return a dictionary with
        # 1. tool
        # 2. acceptable percentage
        # 3. default threshold
        # 4. command map
        # 5. actions (track_modif, exclude_some, create_new_track)
        return {
            "tool": self.tool,
            "acceptable_percentage": self.acceptable_percentage,
            "default_threshold": self.default_threshold,
            "command_map": self.command_map,
            "actions": self.actions
        }


        return {
            self.tool, self.acceptable_percentage, self.default_threshold, self.command_map
        }
      except (KeyError, ValueError) as e:
            raise e
    
    def validate_smb_commands(self, track_commands, exclude_commands):

        # Handle missing TrackCommands (default to empty list)
        track_commands = track_commands if track_commands is not None else []
        exclude_commands = exclude_commands if exclude_commands is not None else []

        # Use an integer where 2^i indicates if i-th command is present
        present_track_cmds = 0
        present_exclude_cmds = 0

        #Checks for duplicate track commands
        for command in track_commands:
            if "command" not in command:
                raise ValueError(f"Missing 'command' key in TrackCommands: {command}")
            try:
                cmd = command["command"]
                if cmd in ALL_SMB_CMDS:
                    if present_track_cmds & (1 << ALL_SMB_CMDS[cmd]):
                        warnings.warn(f"Command {cmd} is duplicated in track commands.", UserWarning)
                        continue
                    if "threshold" in command and (not isinstance(command["threshold"], (int, float)) or command["threshold"] < 0):
                        raise ValueError(f"Invalid threshold value in track command: {command}")
                    present_track_cmds |= (1 << ALL_SMB_CMDS[cmd])
                else:
                    raise ValueError(f"Command {cmd} not found in ALL_SMB_CMDS.")
            except (TypeError, KeyError):
                raise ValueError(f"Invalid track command format: {command}")
            
        #Check for duplicate exclude commands
        for cmd in exclude_commands:
            try:
                if cmd in ALL_SMB_CMDS:
                    if present_exclude_cmds & (1 << ALL_SMB_CMDS[cmd]):
                        warnings.warn(f"Command {cmd} is duplicated in exclude commands.", UserWarning)
                        continue 
                    present_exclude_cmds |= (1 << ALL_SMB_CMDS[cmd])
                else:
                    raise ValueError(f"Command {cmd} not found in ALL_SMB_CMDS.")
            except (TypeError, KeyError):
                raise ValueError(f"Invalid exclude command format: {command}")

        # Check for duplicate commands between track and exclude
        for command in exclude_commands:
            try:
                cmd = command
                if cmd in ALL_SMB_CMDS:
                    if present_track_cmds & (1 << ALL_SMB_CMDS[cmd]):
                        raise ValueError(f"Command {cmd} is duplicated in track or exclude commands. It is unclear if Command {cmd} should be tracked or excluded.")
                else:
                    raise ValueError(f"Command {cmd} not found in ALL_SMB_CMDS.")
            except (TypeError, KeyError):
                raise ValueError(f"Invalid exclude command format: {command}")

    def exclude_some(self, exclude_commands):
        """Exclude commands from parsed_data."""
        for command in exclude_commands:
            if command in self.command_map:
                del self.command_map[command]
            # if duplicated command in exclude commands, ignore it

    def track_modif(self, track_commands):
        """Modify tracked commands' thresholds."""
        #We consider the threshold specified by the last track command in case of duplicates
        for command in track_commands:
            cmd = command.get("command")
            threshold = command.get("threshold", self.default_threshold)
            self.command_map[cmd] = threshold

    def create_new_track(self, track_commands):
        """Create a new tracking list with specific thresholds."""
        self.command_map = {}
        for command in track_commands:
            cmd = command.get("command")
            threshold = command.get("threshold", self.default_threshold)
            self.command_map[cmd] = threshold

class ErrorConfigParser(AnomalyConfigParser):
    def parse(self):
        # Placeholder for error-specific logic
        return {}

# eBPF Launcher Base Class
class EBPFLauncher(ABC):
    def __init__(self, config):
        self.config = config

    @abstractmethod
    def launch(self):
        pass

# eBPF Launcher for Latency
class LatencyEBPFLauncher(EBPFLauncher):
    def launch(self):
        print("Launching Latency eBPF")
        #We may need to create a seperate process or run this cmd or whatever
        #I will do that later after i get the architecture
        #for now, i'll only think abt what cmd im supposed to run

        self.tool = self.config.get("tool")
        #for now im assuming which ever tool we use will have same parameter format as smbslower

        self.default_threshold = self.config.get("default_threshold")
        min_threshold = self.default_threshold
        #iterate over the command map and get the min threshold
        for command, threshold in self.config.get("command_map", {}).items():
            if threshold < min_threshold:
                min_threshold = threshold

        #now ill decide which cmds to include in the search
        #i will assume only the -c parameter is working and -x doesnt work
        #iterate over the command map and get the commands to include
        include_commands = []
        for command, threshold in self.config.get("command_map", {}).items():
            include_commands.append(ALL_SMB_CMDS[command])

        cmd = f"{self.tool} -m {min_threshold} -c {','.join(map(str, include_commands))}"
        print(f"Running command: {cmd}")

        # Start the eBPF script as a background process
        process = subprocess.Popen(cmd, shell=True)
        print(f"eBPF process started with PID: {process.pid}")
        self.ebpf_process = process
        

# eBPF Launcher for Error
class ErrorEBPFLauncher(EBPFLauncher):
    def launch(self):
        print("Launching Error eBPF with config:", self.config)
        # TODO: Add actual launch logic here

# eBPF Launcher Factory
class EBPFLauncherFactory:
    @staticmethod
    def get_launcher(anomaly_type, config):
        if anomaly_type == "Latency":
            return LatencyEBPFLauncher(config)
        elif anomaly_type == "Error":
            return ErrorEBPFLauncher(config)
        else:
            raise ValueError(f"Unsupported anomaly type for eBPF: {anomaly_type}")



# Main Entry Point
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["Guardian", "Watcher"])
    # this file is in a folder called src, config.yaml is in a sibling folder called config
    parser.add_argument("--config-path", default=os.path.join(os.path.dirname(__file__), "../config/config.yaml"))
    parser.add_argument("--continuous", action="store_true")
    args = parser.parse_args()

    controller = AODController(mode=args.mode, config_path=args.config_path, continuous=args.continuous)
    try:
        controller.run()
    except Exception as e:
        print(f"Error: {e}") 