# PhotoFlow: A Command-Line Photo and Video Workflow Tool

**PhotoFlow** is a powerful, command-line-driven tool designed to streamline the process of organizing, cleaning, and processing large collections of digital photos and videos. It provides a modular and configurable workflow for photographers and archivists.

## Features

- **All-in-One Tool:** A single script, `photoflow`, provides access to all workflow stages.
- **Phased Workflow:** Functionality is broken down into clearly named subcommands (e.g., `dedup`, `timeshift`) that follow a logical, numbered sequence to guide the user through the process.
- **Safe by Design:**
    - **Dry Run Mode:** A global `--dry-run` flag allows you to preview all changes without modifying any files.
    - **Safe Deletion:** Duplicates are moved to a trash folder, not deleted directly.
    - **GPS Protection:** Never overwrites existing GPS data.
- **Configurable:** Manage file formats and other settings through a simple JSON configuration file.
- **Robust:** Includes pre-flight checks for dependencies and permissions, and logs all errors to a dedicated file for easy debugging.
- **User-Friendly:** Provides clear, verbose output and visual progress bars for long operations.

## Requirements

- **Python 3.8+**
- **ExifTool:** You must have a recent version of `exiftool` installed and available in your system's `PATH`. You can get it from the [official ExifTool website](https://exiftool.org/).

## Installation

It is recommended to install PhotoFlow using `pip`.

1.  **Clone the repository:**
    ```bash
    git clone <repository_url>
    cd photoflow
    ```
2.  **Install with pip:**
    This command will install the script and its Python dependencies (like `tqdm`).
    ```bash
    pip install .
    ```
3.  **Verify installation:**
    After installation, the `photoflow` command should be available in your terminal.
    ```bash
    photoflow --help
    ```

## Quick Start

The script is run from the command line, specifying a subcommand for the task you want to perform. All operations are run from within the directory containing the photos you want to process.

When run with no command, it now correctly displays a detailed help message explaining all available commands and the recommended workflow.

```bash
# Get help for all commands and see the workflow
photoflow

# Get help for a specific command
photoflow geotag --help

# Do a dry run of the 'by-date' command to see what it would do
photoflow by-date --dry-run
```

## Global Options

- `--dry-run`: Simulate the command without making any actual changes to your files.
- `-v`, `--verbose`: Enable verbose output for detailed debugging information.

## Configuration

The first time you run `photoflow`, it will automatically create a configuration file at `~/.config/photoflow/config.json`. You can edit this file to customize the script's behavior.

A default configuration looks like this:
```json
{
  "workspace_dir": "_photo_workspace",
  "duplicates_trash_dir": "_duplicates_trash",
  "file_formats": {
    "raw": ["srw", "cr2", "nef", "arw", "dng"],
    "image": ["jpg", "jpeg", "png", "tif", "tiff", "heic"],
    "video": ["mp4", "mov", "avi", "mts"]
  },
  "dedup": {
    "checksum_algorithm": "md5"
  }
}
```

## Workflow and Commands

The script's commands are divided into two main groups:

### Workflow Phases
These commands are designed to be run in sequence for a complete photo management workflow, from initial cleanup to final organization.

#### 1. `dedup`
Finds and separates duplicate files.
- **What it does:** Recursively scans all files in the current directory, regardless of type. It calculates a checksum for each file and moves duplicates to a trash directory (`_duplicates_trash` by default). It also generates a report for files with the same name but different content.

```bash
photoflow dedup
```

#### 2. `timeshift`
Corrects the EXIF timestamps on your photos if the camera clock was wrong.
- **Usage:** `photoflow timeshift --days 1 --hours 2`
- **Advanced Usage:** `photoflow timeshift --offset "+=0:0:0 1:30:0"`

#### 3. `pair-jpegs`
For RAW+JPEG shooters, this command separates the "extra" JPEGs.
- **What it does:** Finds RAW/JPEG pairs, verifies their metadata, and moves the JPEG to an `_extra_jpgs` folder.

```bash
photoflow pair-jpegs
```

#### 4. `by-date`
Organizes your cleaned-up files into a neat, date-based folder structure.
- **What it does:** Moves all your photos and videos into a `by-date/YYYY-MM-DD/` directory structure based on their EXIF timestamp.

```bash
photoflow by-date
```

#### 5. `geotag`
Applies GPS coordinates to your photos using a GPX track log.
- **Two-Pass System:** This command now runs a two-pass process to maximize geotagging.
  1.  **Pass 1 (Interpolation):** Applies GPS data using standard time-based interpolation.
  2.  **Pass 2 (Extrapolation):** For any files that were not tagged, it makes a second attempt by assigning the most recent known GPS location (extrapolating up to 24 hours).
- **Safety:** Automatically skips files that already have GPS data. Files successfully tagged in Pass 2 are moved to a `last-gps` folder for review. Any files that fail both passes are moved to a `no-gps` folder.
- **Usage:**

```bash
photoflow geotag --gpx-dir /path/to/gpx-files --timezone -05:00
```

#### 6. `to-develop`
For advanced workflows (e.g., RAW -> TIF -> JPG), this command identifies what work is left to do.
- **What it does:** Reports which RAW files are missing a TIF, and which TIF files are missing a final standard JPEG.

```bash
photoflow to-develop
```

### Miscellaneous Commands
These are standalone utility commands that can be run at any time.

#### `move-no-gps`
Finds and separates all photos that do not have any GPS information.
- **What it does:** Recursively scans the current directory for photo files (e.g., JPG, RAW) and checks their metadata. Any photo without GPS tags is moved to a `non-gps` folder, preserving its original directory structure. This is useful for isolating files that need to be geotagged manually.

```bash
photoflow move-no-gps
```
