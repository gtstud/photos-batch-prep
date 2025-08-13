# Photo Workflow Script Specification

This document outlines the technical specification for the `photoflow.py` script, a command-line tool for managing and processing digital photo and video collections.

## 1. Overview

The `photoflow.py` script is a single, unified tool that replaces a series of individual shell scripts. It provides a structured, command-line interface for common photo management tasks such as deduplication, timestamp correction, geotagging, and file organization.

The script is designed to be:
- **Modular:** Functionality is separated into distinct, numbered subcommands that represent phases of the workflow.
- **Configurable:** Key parameters like file types and directory names are managed via a central configuration file.
- **Safe:** Operations that modify or delete files are logged, and sensitive operations (like geotagging) include safety checks to prevent data loss.
- **User-Friendly:** Provides clear help messages (including a workflow overview) and generates detailed reports.

## 2. Core Components

### 2.1. Main Script (`photoflow.py`)

- **Language:** Python 3
- **Dependencies:** None beyond the standard library. It will call `exiftool` as an external command.
- **Entry Point:** A `main()` function handles command-line argument parsing and dispatches to the appropriate subcommand function.

### 2.2. Configuration File

- **Location:** `~/.config/photoflow/config.json` on Linux/macOS. A platform-specific location will be used for other OSes.
- **Format:** JSON
- **Content:**
  - `workspace_dir`: The name of the directory to store logs and reports (e.g., `_photo_workspace`).
  - `file_formats`: A dictionary mapping categories to lists of file extensions (case-insensitive).
    - `raw`: e.g., `["srw", "cr2", "nef", "arw"]`
    - `image`: e.g., `["jpg", "jpeg", "png", "tif", "tiff"]`
    - `video`: e.g., `["mp4", "mov", "avi"]`
  - `dedup`: Configuration for the `dedup` command.
    - `checksum_algorithm`: e.g., `md5`
- **Behavior:** The script will automatically create a default configuration file on first run if one does not exist.

### 2.3. External Dependencies

- **`exiftool`:** This command-line utility is required for all EXIF data manipulation. The script will assume `exiftool` is available in the system's `PATH` and will perform a check on startup.

## 3. Command-Line Interface

The script uses Python's `argparse` module to implement a main command with several subcommands named to reflect the workflow phases. When run without arguments, it displays a help message outlining the recommended workflow.

```
photoflow.py <subcommand> [options]
```

### 3.1. Global Options

- `--help` / `-h`: Display help information for the main command or a specific subcommand.

### 3.2. Subcommands

#### `01-dedup`
- **Description:** Phase 1: Finds duplicate files and files with naming conflicts.
- **Functionality:**
  1. Scans the current directory recursively for all files.
  2. Calculates a checksum (e.g., MD5) for each file.
  3. Generates a shell script (`action01-deduplicate_commands.sh`) with `rm` commands for files that are exact duplicates (same name, size, and checksum).
  4. Generates a text report (`report01-conflicting_versions.txt`) listing files that have the same name but different checksums.

#### `02-timeshift`
- **Description:** Phase 2: Shifts EXIF timestamps for a batch of files.
- **Options:**
  - `--offset "SPEC"`: The time shift specification string (e.g., `"+=1:30:0"`). This is a required argument.
- **Functionality:**
  1. Calls `exiftool -AllDates<OFFSET>` on all files in the current directory.
  2. Moves files that `exiftool` cannot process to a `_non_photos` directory.
  3. Moves files that have no date tags to update to an `_untagged_photos` directory.
  4. Moves `exiftool`'s `*_original` backup files to an `_originals` directory.

#### `03-pair-jpegs`
- **Description:** Phase 3: Identifies RAW+JPEG pairs and separates the JPEG file.
- **Functionality:**
  1. Searches for RAW files based on the `file_formats.raw` configuration.
  2. For each RAW file, looks for a JPEG with the same base name.
  3. If a pair is found, it verifies them by comparing EXIF tags (`CameraModelID` and `DateTimeOriginal` within a 1s tolerance).
  4. If verified, moves the JPEG file to an `_extra_jpgs` directory.

#### `04-by-date`
- **Description:** Phase 4: Organizes files into a `YYYY-MM-DD` directory structure.
- **Functionality:**
  1. Moves all processable files into a temporary `src` directory.
  2. Uses `exiftool` to rename and move files from `src` into a `by-date/YYYY-MM-DD/` structure based on the `DateTimeOriginal` tag.
  3. Reports any files left in `src` (likely due to missing EXIF date) and cleans up the directory.

#### `05-geotag`
- **Description:** Phase 5: Applies GPS data to files from GPX tracks.
- **Options:**
  - `--gpx-dir PATH`: Path to the directory containing GPX files (required).
  - `--timezone OFFSET`: Timezone offset for `DateTimeOriginal` (e.g., `+02:00`) (required).
- **Functionality (with overwrite protection):**
  1. Scans all files in the `by-date` directory.
  2. **Safety Check:** For each file, it uses `exiftool` to check if GPS coordinates (`GPSLatitude`) already exist.
  3. Files that **already have GPS data** are moved to a temporary `_already_geotagged` directory, preserving their path.
  4. `exiftool` is then run on the `by-date` directory to geotag the remaining files (those without GPS data).
  5. The files from `_already_geotagged` are moved back to their original locations.

#### `06-to-develop`
- **Description:** Phase 6: Identifies folders that require further processing steps in a RAW development workflow.
- **Functionality:**
  1. **Check 1:** Finds all RAW files and checks if a corresponding TIF/TIFF file exists in any subfolder of the RAW file's directory. It reports the folders of RAWs that are missing a TIF.
  2. **Check 2:** Finds all TIF/TIFF files and checks if a corresponding `*__std.jpg` file exists in the parent directory. It reports the folders of TIFs that are missing this final JPEG.

## 4. Logging and Reporting

- All operations will be logged to files within the `workspace_dir` (`_photo_workspace`).
- Each subcommand will generate its own set of logs and summary reports, prefixed with the module name (e.g., `p05-gps-log01-details.txt`).
- The script will print a summary of actions to the console and direct the user to the log files for more details.
