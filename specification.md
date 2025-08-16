# Photo Workflow Script Specification

This document outlines the technical specification for the `photoflow.py` script, a command-line tool for managing and processing digital photo and video collections.

## 1. Overview

The `photoflow.py` script is a single, unified tool that provides a structured, command-line interface for common photo management tasks.

The script is designed to be:
- **Modular:** Functionality is separated into distinct, numbered subcommands that represent phases of the workflow.
- **Configurable:** Key parameters are managed via a central configuration file.
- **Safe:** Includes a `--dry-run` mode, moves duplicates to a trash folder instead of deleting, and protects existing GPS data.
- **Robust:** Performs pre-flight checks for dependencies (exiftool) and write permissions. All warnings and errors are logged to a dedicated file.
- **User-Friendly:** Provides a workflow overview in its help text, shows progress bars for long operations, and supports verbose logging for debugging.

## 2. Core Components

### 2.1. Main Script (`photoflow.py`)

- **Language:** Python 3.8+
- **Dependencies:**
    - `tqdm`: For displaying progress bars.
- **External Dependencies:**
    - `exiftool`: Required for all EXIF data manipulation. The script checks for its existence in the system `PATH` on startup.

### 2.2. Packaging (`pyproject.toml`)

- The script is packaged using `setuptools`.
- It can be installed via `pip install .`, which also handles the `tqdm` dependency.
- Installation registers the `photoflow` command, making it accessible system-wide.

### 2.3. Configuration File

- **Location:** `~/.config/photoflow/config.json`.
- **Format:** JSON.
- **Content:** Includes paths for the workspace and trash directories, file format definitions, and checksum algorithm.
- **Behavior:** The script automatically creates a default configuration file on first run if one does not exist.

## 3. Command-Line Interface

The script uses `argparse` to implement a main command with several subcommands.

```
photoflow <subcommand> [options]
```

### 3.1. Global Options

- `--help` / `-h`: Display help information.
- `--verbose` / `-v`: Enable verbose debug output. All `exiftool` calls and other detailed info will be logged.
- `--dry-run`: Simulate the command. The script will report all actions it *would* take without modifying any files.

### 3.2. Subcommands

The script's subcommands are organized into "Workflow Phases" and "Miscellaneous Commands" in the command-line interface.

#### `dedup`
- **Description:** Phase 1: Finds duplicate files and moves them to a trash directory.
- **Functionality:**
  1. Scans the current directory recursively for **all file types**.
  2. Calculates a checksum for each file.
  3. Moves files with identical content to the `duplicates_trash_dir`.
  4. Generates a report for files with the same name but different checksums.

#### `timeshift`
- **Description:** Phase 2: Shifts EXIF timestamps for a batch of files.
- **Options:**
  - `--days`, `--hours`, `--minutes`, `--seconds`: User-friendly flags to specify the shift.
  - `--offset "SPEC"`: The advanced `exiftool` time shift specification string.
- **Functionality:**
  1. Calculates the final offset string.
  2. Calls `exiftool -AllDates<OFFSET>` on all files.
  3. Sorts files into output directories based on the outcome.

#### `pair-jpegs`
- **Description:** Phase 3: Identifies RAW+JPEG pairs and separates the JPEG file.

#### `by-date`
- **Description:** Phase 4: Organizes files into a `YYYY-MM-DD` directory structure.

#### `geotag`
- **Description:** Phase 5: Applies GPS data to files from GPX tracks using a two-pass system.
- **Functionality:**
  1. **Initial Scan:** Identifies all files in the `by-date` directory that do not have GPS data.
  2. **Pass 1 (Interpolation):** Runs `exiftool` with standard `-geotag` options.
  3. **Re-scan and Move:** Identifies files that failed Pass 1 and moves them to the `last-gps` directory, preserving their relative path.
  4. **Pass 2 (Extrapolation):** Runs `exiftool` on the files in `last-gps` with `-api GeoMaxIntSecs=0 -api GeoMaxExtSecs=86400` to apply the last known location.
  5. **Final Move:** Any files that still lack GPS data are moved from `last-gps` to a `no-gps` directory.

#### `to-develop`
- **Description:** Phase 6: Identifies folders that require further processing.

#### `move-no-gps`
- **Description:** Miscellaneous: Moves all photo files without GPS data to a `non-gps` directory.
- **Functionality:**
  1. Recursively scans the current directory for photo files (based on `file_formats` in config).
  2. Uses `exiftool` to check for `GPSLatitude`.
  3. Moves any photo file without GPS data to the `non-gps` subfolder, preserving the directory structure.

## 4. Logging and Reporting

- A `logging` instance is used for all output.
- **Console:** Logs `INFO` and higher by default. `DEBUG` level is enabled with `--verbose`.
- **Error Log File:** All `WARNING` and `ERROR` level messages are automatically logged to `photoflow-errors.log` inside the workspace directory for persistent, detailed error tracking.
- **Pre-flight Checks:** The script will fail early if `exiftool` is not found or if it lacks write permissions in the current directory.
