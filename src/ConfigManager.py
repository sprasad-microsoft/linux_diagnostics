from shared_data import *
import yaml
import warnings


class ConfigManager:

    def __init__(self, config_path: str):
        try:
            with open(config_path, "r") as file:
                config_data = yaml.safe_load(file)
        except FileNotFoundError:
            raise RuntimeError(f"Config file not found: {config_path}")
        except yaml.YAMLError as e:
            raise RuntimeError(f"YAML parsing error in config file: {e}")

        # Parse watcher
        watcher = WatcherConfig(actions=config_data["watcher"]["actions"])

        # Parse guardian anomalies
        anomalies = {}
        for name, anomaly in config_data["guardian"]["anomalies"].items():

            # depending on the type of anomaly, i want to call different functions
            if anomaly["type"] == "Latency":
                track = self.get_latency_track_cmds(anomaly)
            elif anomaly["type"] == "Error":
                track = self.get_error_track_cmds(anomaly)

            print(f"track: {track}")
            # Check if track is empty after all logic
            if not track or (isinstance(track, dict) and len(track) == 0):
                raise ValueError(
                    f"No items to track for anomaly '{name}' after applying config logic."
                )

            anomalies[name] = AnomalyConfig(
                type=anomaly["type"],
                tool=anomaly["tool"],
                acceptable_percentage=anomaly["acceptable_percentage"],
                default_threshold_ms=anomaly.get("default_threshold_ms"),
                track=track,
                actions=anomaly.get("actions", []),
            )
        guardian = GuardianConfig(anomalies=anomalies)

        # Build the top-level config
        self.data = Config(
            watch_interval_sec=config_data["watch_interval_sec"],
            aod_output_dir=config_data["aod_output_dir"],
            watcher=watcher,
            guardian=guardian,
            cleanup=config_data["cleanup"],
            audit=config_data["audit"],
        )

    def validate_cmds(self, all_codes, track_codes, exclude_codes):

        # check if any track_codes are duplicated
        present_track_codes = set()
        for code in track_codes:
            if code not in all_codes:
                raise ValueError(f"Code {code} not found in error codes.")
            if code in present_track_codes:
                warnings.warn(f"Code {code} is duplicated in track codes.", UserWarning)
            present_track_codes.add(code)

        # check if any exclude_codes are duplicated
        present_exclude_codes = set()
        for code in exclude_codes:
            if code not in all_codes:
                raise ValueError(f"Code {code} not found in error codes.")
            if code in present_exclude_codes:
                warnings.warn(f"Code {code} is duplicated in exclude codes.", UserWarning)
            present_exclude_codes.add(code)

        # check if any track_codes are in exclude_codes
        for code in track_codes:
            if code in exclude_codes:
                raise ValueError(
                    f"Code {code} is duplicated in track and exclude codes. It is unclear if Code {code} should be tracked or excluded."
                )

    def validate_smb_commands(self, track_commands, exclude_commands):

        # Handle missing TrackCommands (default to empty list)
        track_commands = track_commands if track_commands is not None else []
        exclude_commands = exclude_commands if exclude_commands is not None else []

        # If both are empty, nothing to validate
        if not track_commands and not exclude_commands:
            return

        # Use an integer where 2^i indicates if i-th command is present
        present_track_cmds = 0
        present_exclude_cmds = 0

        # Checks for duplicate track commands
        for command in track_commands:
            if "command" not in command:
                raise ValueError(f"Missing 'command' key in TrackCommands: {command}")
            try:
                cmd = command["command"]
                if cmd in ALL_SMB_CMDS:
                    if present_track_cmds & (1 << ALL_SMB_CMDS[cmd]):
                        warnings.warn(
                            f"Command {cmd} is duplicated in track commands.", UserWarning
                        )
                        continue
                    if "threshold" in command and (
                        not isinstance(command["threshold"], (int, float))
                        or command["threshold"] < 0
                    ):
                        raise ValueError(f"Invalid threshold value in track command: {command}")
                    present_track_cmds |= 1 << ALL_SMB_CMDS[cmd]
                else:
                    raise ValueError(f"Command {cmd} not found in ALL_SMB_CMDS.")
            except (TypeError, KeyError):
                raise ValueError(f"Invalid track command format: {command}")

        # Check for duplicate exclude commands
        for cmd in exclude_commands:
            try:
                if cmd in ALL_SMB_CMDS:
                    if present_exclude_cmds & (1 << ALL_SMB_CMDS[cmd]):
                        warnings.warn(
                            f"Command {cmd} is duplicated in exclude commands.", UserWarning
                        )
                        continue
                    present_exclude_cmds |= 1 << ALL_SMB_CMDS[cmd]
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
                        raise ValueError(
                            f"Command {cmd} is duplicated in track or exclude commands. It is unclear if Command {cmd} should be tracked or excluded."
                        )
                else:
                    raise ValueError(f"Command {cmd} not found in ALL_SMB_CMDS.")
            except (TypeError, KeyError):
                raise ValueError(f"Invalid exclude command format: {command}")

    def get_track_codes(self, mode, all_codes, track_codes, exclude_codes):

        if mode == "trackonly":
            return {code: None for code in track_codes}
        else:
            exclude_set = set(exclude_codes)
            return {code: None for code in all_codes if code not in exclude_set}

    def get_latency_track_cmds(self, anomaly):
        track_commands = anomaly.get("track_commands", []) or []
        exclude_commands = anomaly.get("exclude_commands", []) or []
        latency_mode = anomaly.get("mode", "all")

        # Validate latency mode constraints
        if latency_mode == "trackonly" and exclude_commands:
            warnings.warn("Exclude commands will be ignored in trackonly mode.")
            exclude_commands = []
        elif latency_mode == "excludeonly" and track_commands:
            warnings.warn("Track commands will be ignored in excludeonly mode.")
            track_commands = []

        self.validate_smb_commands(track_commands, exclude_commands)

        # Initialize all commands to -1
        command_map = {cmd: -1 for cmd in ALL_SMB_CMDS}
        default_threshold = anomaly.get("default_threshold_ms", 10)

        # Apply thresholds based on mode
        if latency_mode == "trackonly":
            command_map = {}
            for cmd in track_commands:
                command = cmd["command"]
                threshold = cmd.get("threshold", default_threshold)
                command_map[command] = threshold
        elif latency_mode == "excludeonly":
            for cmd in command_map:
                command_map[cmd] = default_threshold
            for cmd in exclude_commands:
                if cmd in command_map:
                    del command_map[cmd]
            print("haha")
        else:  # mode == "all"
            for cmd in command_map:
                command_map[cmd] = default_threshold
            for cmd in track_commands:
                command = cmd["command"]
                threshold = cmd.get("threshold", default_threshold)
                command_map[command] = threshold
            for cmd in exclude_commands:  # delete if it is over here
                if cmd in command_map:
                    del command_map[cmd]

        return command_map

    def get_error_track_cmds(self, anomaly):

        track_codes = anomaly.get("track_codes", [])
        exclude_codes = anomaly.get("exclude_codes", [])
        error_mode = anomaly.get("mode", "all")

        # Validate error mode constraints
        if error_mode == "trackonly" and exclude_codes:
            warnings.warn("Exclude codes will be ignored in trackonly mode.")
            exclude_codes = []
        elif error_mode == "excludeonly" and track_codes:
            warnings.warn("Track codes will be ignored in excludeonly mode.")
            track_codes = []

        # Validate track and exclude codes
        self.validate_cmds(error_codes, track_codes, exclude_codes)

        return self.get_track_codes(error_mode, error_codes, track_codes, exclude_codes)
