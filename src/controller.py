import argparse
import yaml
import os
import psutil
from abc import ABC, abstractmethod

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
    def execute(self):
        anomalies = self.config.get("Anomalies", {})
        for anomaly_type, section in anomalies.items():
            parser = AnomalyParserFactory.get_parser(anomaly_type, section)
        
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
            raise ValueError("Cannot have exclude commands in trackonly mode.")
            exclude_commands = []
        elif self.latency_mode == "excludeonly" and track_commands:
            raise ValueError("Cannot have track commands in excludeonly mode.")
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
            elif self.latency_mode == "trackonly":
                self.create_new_track(track_commands)
            elif self.latency_mode == "excludeonly":
                self.exclude_some(exclude_commands)
            else:
                raise ValueError("Invalid latency mode. Must be 'all', 'trackonly', or 'excludeonly'.")

        # return tool, acceptable percentage, default threshold, and command map
        self.acceptable_percentage = self.config.get("AcceptablePercentage")
        self.tool = self.config.get("Tool")

        #only for degugging purposes
        print(f"Tool: {self.tool}, Acceptable Percentage: {self.acceptable_percentage}, Default Threshold: {self.default_threshold}")
        #print command map in table format
        print("Command Map:")
        print("{:<30} {:<10}".format("Command", "Threshold"))
        for command, threshold in self.command_map.items():
            print("{:<30} {:<10}".format(command, threshold))

        return {
            self.tool, self.acceptable_percentage, self.default_threshold, self.command_map
        }
      except (KeyError, ValueError) as e:
            raise e
    
    def validate_smb_commands(self, track_commands, exclude_commands):

        all_smb_cmds = {
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
        }

        # Handle missing TrackCommands (default to empty list)
        track_commands = track_commands if track_commands is not None else []
        exclude_commands = exclude_commands if exclude_commands is not None else []

        # Use an integer where 2^i indicates if i-th command is present
        present_cmds = 0
        present_exclude_cmds = 0

        #Check for duplicate exclude commands
        for cmd in exclude_commands:
            try:
                if cmd in all_smb_cmds:
                    if present_exclude_cmds & (1 << all_smb_cmds[cmd]):
                        raise ValueError(f"Command {cmd} is duplicated in exclude commands.")
                    present_exclude_cmds |= (1 << all_smb_cmds[cmd])
                else:
                    raise ValueError(f"Command {cmd} not found in all_smb_cmds.")
            except (TypeError, KeyError):
                raise ValueError(f"Invalid exclude command format: {command}")

        #Checks for duplicate track commands
        for command in track_commands:
            if "command" not in command:
                raise ValueError(f"Missing 'command' key in TrackCommands: {command}")
            try:
                cmd = command["command"]
                if cmd in all_smb_cmds:
                    if present_cmds & (1 << all_smb_cmds[cmd]):
                        raise ValueError(f"Command {cmd} is duplicated in track commands.")
                    if "threshold" in command and (not isinstance(command["threshold"], (int, float)) or command["threshold"] < 0):
                        raise ValueError(f"Invalid threshold value in track command: {command}")
                    present_cmds |= (1 << all_smb_cmds[cmd])
                else:
                    raise ValueError(f"Command {cmd} not found in all_smb_cmds.")
            except (TypeError, KeyError):
                raise ValueError(f"Invalid track command format: {command}")
            
        # Check for duplicate commands between track and exclude
        for command in exclude_commands:
            try:
                cmd = command
                if cmd in all_smb_cmds:
                    if present_cmds & (1 << all_smb_cmds[cmd]):
                        raise ValueError(f"Command {cmd} is duplicated in track or exclude commands.")
                    present_cmds |= (1 << all_smb_cmds[cmd])
                else:
                    raise ValueError(f"Command {cmd} not found in all_smb_cmds.")
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

# Main Entry Point
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["Guardian", "Watcher"])
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--continuous", action="store_true")
    args = parser.parse_args()

    controller = AODController(mode=args.mode, config_path=args.config, continuous=args.continuous)
    try:
        controller.run()
    except Exception as e:
        print(f"Error: {e}") 