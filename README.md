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

The tool is designed around a logical, numbered workflow. Here are the main commands:

### 1. `dedup`
Finds duplicate files.
- **What it does:** Scans for files that have identical content (based on size and checksum, regardless of filename). The first-found file is kept, and subsequent duplicates are moved to a trash directory (`_duplicates_trash` by default). It also generates a report for files with the same name but different content.

```bash
photoflow dedup
```

### 2. `timeshift`
Corrects the EXIF timestamps on your photos if the camera clock was wrong.
- **Usage:** Provide a time shift using simple flags or an advanced offset string.
  - To add 1 day and 2 hours: `photoflow timeshift --days 1 --hours 2`
  - To subtract 30 minutes: `photoflow timeshift --minutes -30`
- **Advanced Usage:** You can also provide a raw `exiftool` offset string. For example, to add 1 hour and 30 minutes:
```bash
photoflow timeshift --offset "+=0:0:0 1:30:0"
```

### 3. `pair-jpegs`
For RAW+JPEG shooters, this command separates the "extra" JPEGs.
- **What it does:** Finds RAW/JPEG pairs, verifies them, and moves the JPEG to an `_extra_jpgs` folder.

```bash
photoflow pair-jpegs
```

### 4. `by-date`
Organizes your cleaned-up files into a neat, date-based folder structure.
- **What it does:** Moves all your photos and videos into a `by-date/YYYY-MM-DD/` directory structure.

```bash
photoflow by-date
```

### 5. `geotag`
Applies GPS coordinates to your photos using a GPX track log.
- **Safety Feature:** This command automatically detects and **skips** any files that are already geotagged. It **will not** overwrite existing GPS data.
- **Usage:**

```bash
photoflow geotag --gpx-dir /path/to/gpx-files --timezone -05:00
```

### 6. `to-develop`
For advanced workflows (e.g., RAW -> TIF -> JPG), this command identifies what work is left to do.
- **What it does:** Scans your folders and reports which RAW files are missing a TIF, and which TIF files are missing a final standard JPEG.

```bash
photoflow to-develop
```
