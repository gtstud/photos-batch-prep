# PhotoFlow: A Command-Line Photo and Video Workflow Tool

**PhotoFlow** is a powerful, command-line-driven tool designed to streamline the process of organizing, cleaning, and processing large collections of digital photos and videos. It replaces a series of shell scripts with a single, robust Python application, providing a modular and configurable workflow for photographers and archivists.

## Features

- **All-in-One Tool:** A single script, `photoflow.py`, provides access to all workflow stages.
- **Phased Workflow:** Functionality is broken down into clearly numbered subcommands (e.g., `01-dedup`, `02-timeshift`) to guide the user through the process.
- **Safe and Non-Destructive by Default:** Generates reports and action scripts before making changes. Critical operations include safety checks to prevent data loss (e.g., does not overwrite existing GPS data).
- **Configurable:** Manage file formats and other settings through a simple JSON configuration file.
- **Detailed Logging:** Creates comprehensive logs and summary reports for every operation, stored in a local `_photo_workspace` directory.

## Requirements

- **Python 3.6+**
- **ExifTool:** You must have a recent version of `exiftool` installed and available in your system's `PATH`. You can get it from the [official ExifTool website](https://exiftool.org/).

## Quick Start

The script is run from the command line, specifying a subcommand for the task you want to perform. All operations are run from within the directory containing the photos you want to process.

When run with no command, it will display a detailed help message explaining the recommended workflow.

```bash
# Get help for all commands and see the workflow
python3 photoflow.py

# Get help for a specific command (e.g., geotag)
python3 photoflow.py 05-geotag --help
```

## Configuration

The first time you run `photoflow.py`, it will automatically create a configuration file at `~/.config/photoflow/config.json`. You can edit this file to customize the script's behavior.

A default configuration looks like this:
```json
{
  "workspace_dir": "_photo_workspace",
  "file_formats": {
    "raw": [
      "srw",
      "cr2",
      "nef",
      "arw",
      "dng"
    ],
    "image": [
      "jpg",
      "jpeg",
      "png",
      "tif",
      "tiff",
      "heic"
    ],
    "video": [
      "mp4",
      "mov",
      "avi",
      "mts"
    ]
  },
  "dedup": {
    "checksum_algorithm": "md5"
  }
}
```

## Workflow and Commands

The tool is designed around a logical, numbered workflow. Here are the main commands and their purpose:

### 1. `01-dedup`
Finds duplicate files before you start processing.
- **What it does:** Scans for files that are exact duplicates (name, size, checksum) and for files that have the same name but different content.
- **Output:** Creates a `deduplicate_commands.sh` script to safely remove duplicates and a text report of conflicting files.

```bash
python3 photoflow.py 01-dedup
```

### 2. `02-timeshift`
Corrects the EXIF timestamps on your photos if the camera clock was wrong.
- **What it does:** Applies a time offset to all date/time tags in your photos.
- **Usage:** Provide a time shift string. For example, to add 1 hour and 30 minutes:

```bash
python3 photoflow.py 02-timeshift --offset "+=0:0:0 1:30:0"
```

### 3. `03-pair-jpegs`
For RAW+JPEG shooters, this command separates the "extra" JPEGs that you may not need to keep alongside your RAW files.
- **What it does:** Finds RAW/JPEG pairs, verifies they were taken by the same camera at the same time, and moves the JPEG to an `_extra_jpgs` folder.

```bash
python3 photoflow.py 03-pair-jpegs
```

### 4. `04-by-date`
Organizes your cleaned-up files into a neat, date-based folder structure.
- **What it does:** Moves all your photos and videos into a `by-date/YYYY-MM-DD/` directory structure based on their EXIF creation date.

```bash
python3 photoflow.py 04-by-date
```

### 5. `05-geotag`
Applies GPS coordinates to your photos using a GPX track log from a GPS device or phone.
- **What it does:** Matches photos to the GPX track based on time.
- **Safety Feature:** This command **will not** overwrite GPS data on files that are already geotagged.
- **Usage:**

```bash
python3 photoflow.py 05-geotag --gpx-dir /path/to/your/gpx-files --timezone -05:00
```

### 6. `06-to-develop`
For advanced workflows (e.g., RAW -> TIF -> JPG), this command identifies what work is left to do.
- **What it does:** Scans your folders and reports:
  - Which RAW files are missing a corresponding TIF file.
  - Which TIF files are missing a final `__std.jpg` export.

```bash
python3 photoflow.py 06-to-develop
```
