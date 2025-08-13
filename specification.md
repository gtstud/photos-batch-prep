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

#### `01-dedup`
- **Description:** Phase 1: Finds duplicate files and moves them to a trash directory.
- **Functionality:**
  1. Scans the current directory recursively.
  2. Calculates a checksum for each file, showing progress with `tqdm`.
  3. Moves files that are exact duplicates (same name, size, and checksum) to the `duplicates_trash_dir`.
  4. Generates a text report listing files that have the same name but different checksums.

#### `02-timeshift`
- **Description:** Phase 2: Shifts EXIF timestamps for a batch of files.
- **Options:**
  - `--offset "SPEC"`: The time shift specification string (e.g., `"+=1:30:0"`).
- **Functionality:**
  1. Calls `exiftool -AllDates<OFFSET>` on all files, with a progress bar.
  2. Sorts files into `_non_photos`, `_untagged_photos`, and `_originals` directories based on the outcome.

#### `03-pair-jpegs`
- **Description:** Phase 3: Identifies RAW+JPEG pairs and separates the JPEG file.

#### `04-by-date`
- **Description:** Phase 4: Organizes files into a `YYYY-MM-DD` directory structure.

#### `05-geotag`
- **Description:** Phase 5: Applies GPS data to files from GPX tracks.
- **Functionality (with overwrite protection):**
  1. Scans all files in the `by-date` directory, with a progress bar.
  2. **Safety Check:** Uses `exiftool` to identify files that already have GPS data.
  3. Moves these files to a temporary `_already_geotagged` directory.
  4. Runs `exiftool` to geotag the remaining files.
  5. Moves the already-tagged files back.

#### `06-to-develop`
- **Description:** Phase 6: Identifies folders that require further processing.

## 4. Logging and Reporting

- A `logging` instance is used for all output.
- **Console:** Logs `INFO` and higher by default. `DEBUG` level is enabled with `--verbose`.
- **Error Log File:** All `WARNING` and `ERROR` level messages are automatically logged to `photoflow-errors.log` inside the workspace directory for persistent, detailed error tracking.
- **Pre-flight Checks:** The script will fail early if `exiftool` is not found or if it lacks write permissions in the current directory.
