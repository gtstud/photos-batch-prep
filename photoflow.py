#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
A comprehensive, command-line-driven tool for organizing and processing photo and video collections.
"""

import sys
import argparse
import json
import os
from pathlib import Path

# --- Configuration Management ---

CONFIG_DIR_NAME = "photoflow"
CONFIG_FILE_NAME = "config.json"

def get_config_path() -> Path:
    """Returns the platform-specific path to the configuration file."""
    # Using XDG_CONFIG_HOME standard for Linux
    config_home = os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")
    return Path(config_home) / CONFIG_DIR_NAME / CONFIG_FILE_NAME

def get_default_config() -> dict:
    """Returns the default configuration dictionary."""
    return {
        "workspace_dir": "_photo_workspace",
        "file_formats": {
            "raw": ["srw", "cr2", "nef", "arw", "dng"],
            "image": ["jpg", "jpeg", "png", "tif", "tiff", "heic"],
            "video": ["mp4", "mov", "avi", "mts"],
        },
        "dedup": {
            "checksum_algorithm": "md5"
        }
    }

def load_or_create_config() -> dict:
    """
    Loads the configuration from the user's config directory.
    If the config file doesn't exist, it creates it with default values.
    """
    config_path = get_config_path()
    if not config_path.exists():
        print(f"Configuration file not found. Creating a default one at: {config_path}")
        try:
            config_path.parent.mkdir(parents=True, exist_ok=True)
            default_config = get_default_config()
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(default_config, f, indent=2)
            return default_config
        except IOError as e:
            print(f"Error: Could not create configuration file: {e}", file=sys.stderr)
            sys.exit(1)

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        print(f"Error: Could not read or parse configuration file at {config_path}: {e}", file=sys.stderr)
        print("Please fix or delete the file to allow recreation.", file=sys.stderr)
        sys.exit(1)

# --- Subcommand Functions ---
import hashlib
from collections import defaultdict

def _get_file_hash(filepath, algorithm):
    """Calculates the hash of a file."""
    h = hashlib.new(algorithm)
    try:
        with open(filepath, "rb") as f:
            while True:
                chunk = f.read(h.block_size)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()
    except IOError:
        return None

def handle_dedup(args, config):
    """
    Finds duplicate files and files with naming conflicts.
    """
    print("Running 'dedup' command...")

    workspace_dir = Path.cwd() / config["workspace_dir"]
    workspace_dir.mkdir(exist_ok=True)
    print(f"Workspace directory: {workspace_dir}")

    # Define output files
    dedup_script_path = workspace_dir / "p01-dedup-action01-deduplicate_commands.sh"
    conflict_report_path = workspace_dir / "p01-dedup-report01-conflicting_versions.txt"

    checksum_algo = config["dedup"]["checksum_algorithm"]
    print(f"Using '{checksum_algo}' checksum algorithm.")

    # --- Stage 1: File Hashing ---
    print("Scanning files and calculating checksums...")
    file_data = []
    files_by_name = defaultdict(list)

    for root, dirs, files in os.walk("."):
        # Skip the workspace directory itself
        if str(workspace_dir.resolve()) in str(Path(root).resolve()):
            continue

        for name in files:
            filepath = Path(root) / name
            try:
                size = filepath.stat().st_size
                checksum = _get_file_hash(filepath, checksum_algo)
                if checksum:
                    file_info = {
                        "path": filepath,
                        "name": name,
                        "size": size,
                        "checksum": checksum
                    }
                    file_data.append(file_info)
                    files_by_name[name].append(file_info)
            except OSError as e:
                print(f"Warning: Could not process file {filepath}: {e}", file=sys.stderr)

    print(f"Processed {len(file_data)} files.")

    # --- Stage 2: Deduplication Analysis ---
    files_by_identity = defaultdict(list)
    for info in file_data:
        key = (info["name"], info["size"], info["checksum"])
        files_by_identity[key].append(info)

    duplicates_found = 0
    with open(dedup_script_path, "w", encoding="utf-8") as f:
        f.write("#!/bin/bash\n")
        f.write("# This script contains commands to remove duplicate files.\n")
        f.write("# Kept file is listed as a comment before the 'rm' commands for its duplicates.\n\n")

        for key, items in sorted(files_by_identity.items()):
            if len(items) > 1:
                # Sort by path to have a deterministic "keeper"
                items.sort(key=lambda x: x["path"])
                keeper = items[0]
                duplicates = items[1:]

                f.write(f"# Duplicate set for: Name: {key[0]}, Size: {key[1]}, Checksum: {key[2]}\n")
                f.write(f"# Keeping: '{keeper['path']}'\n")
                for dup in duplicates:
                    f.write(f"rm \"{dup['path']}\"\n")
                    duplicates_found += 1
                f.write("\n")

    if duplicates_found > 0:
        print(f"Found {duplicates_found} duplicate files. 'rm' commands written to: {dedup_script_path}")
        os.chmod(dedup_script_path, 0o755) # Make it executable
    else:
        print("No duplicate files found.")
        dedup_script_path.unlink() # Remove empty script

    # --- Stage 3: Conflict Analysis ---
    conflicts_found = 0
    with open(conflict_report_path, "w", encoding="utf-8") as f:
        f.write("# Report on files with the same name but different checksums.\n\n")

        for name, items in sorted(files_by_name.items()):
            unique_checksums = {item["checksum"] for item in items}
            if len(unique_checksums) > 1:
                conflicts_found += 1
                f.write(f"Filename: '{name}' has {len(items)} instances with {len(unique_checksums)} different versions:\n")
                # Sort by checksum for consistent ordering
                for item in sorted(items, key=lambda x: x["checksum"]):
                    f.write(f"  - Checksum: {item['checksum']}, Size: {item['size']}, Path: '{item['path']}'\n")
                f.write("\n")

    if conflicts_found > 0:
        print(f"Found {conflicts_found} files with conflicting versions. Report written to: {conflict_report_path}")
    else:
        print("No conflicting file versions found.")
        conflict_report_path.unlink() # Remove empty report

    print("'dedup' command complete.")


import re
import subprocess
import shutil

def _move_file_robustly(source_path: Path, target_dir: Path, new_base_name: str = None):
    """Moves a file, handling name collisions by adding a counter."""
    if not source_path.exists():
        return None

    base_name = new_base_name if new_base_name else source_path.name
    extension = "".join(Path(base_name).suffixes)
    stem = base_name.replace(extension, "")

    destination_path = target_dir / base_name
    counter = 0
    while destination_path.exists():
        counter += 1
        new_filename = f"{stem}-{counter:02d}{extension}"
        destination_path = target_dir / new_filename

    try:
        shutil.move(source_path, destination_path)
        return destination_path
    except OSError as e:
        print(f"Error moving file {source_path} to {destination_path}: {e}", file=sys.stderr)
        return None

def handle_timeshift(args, config):
    """
    Shifts EXIF date/time tags in files using exiftool.
    """
    print("Running 'timeshift' command...")

    # --- Argument Validation ---
    offset_pattern = re.compile(r"^[+-]?=\d{1,}:\d{1,}:\d{1,}( \d{1,}:\d{1,}:\d{1,})?$")
    if not offset_pattern.match(args.offset):
        print(f"Error: Invalid offset format: '{args.offset}'. Expected format like '+=Y:M:D H:M:S'.", file=sys.stderr)
        return 1

    # --- Setup ---
    workspace_dir = Path.cwd() / config["workspace_dir"]
    workspace_dir.mkdir(exist_ok=True)

    non_photos_dir = Path.cwd() / "_non_photos"
    untagged_photos_dir = Path.cwd() / "_untagged_photos"
    originals_dir = Path.cwd() / "_originals"

    non_photos_dir.mkdir(exist_ok=True)
    untagged_photos_dir.mkdir(exist_ok=True)
    originals_dir.mkdir(exist_ok=True)

    special_dirs = {workspace_dir.resolve(), non_photos_dir.resolve(), untagged_photos_dir.resolve(), originals_dir.resolve()}

    # --- File Discovery ---
    files_to_process = []
    for root, _, files in os.walk("."):
        root_path = Path(root).resolve()
        if root_path in special_dirs:
            continue
        for name in files:
            # Exclude exiftool temp files
            if not name.endswith(("_original", ".tmp")):
                files_to_process.append(Path(root) / name)

    print(f"Found {len(files_to_process)} files to process.")

    # --- Main Processing Loop ---
    updated_count = 0
    no_tags_count = 0
    error_count = 0

    exiftool_cmd = f"-AllDates{args.offset}"

    for i, filepath in enumerate(files_to_process):
        print(f"\rProcessing {i+1}/{len(files_to_process)}: {filepath.name}", end="", flush=True)
        try:
            result = subprocess.run(
                ["exiftool", "-m", exiftool_cmd, str(filepath)],
                capture_output=True, text=True, check=False
            )

            if "1 image files updated" in result.stdout:
                updated_count += 1
            elif "0 image files updated" in result.stdout:
                if _move_file_robustly(filepath, untagged_photos_dir):
                    no_tags_count += 1
                else:
                    error_count += 1
            else: # Error or unexpected output
                if _move_file_robustly(filepath, non_photos_dir):
                    error_count += 1
                else:
                    error_count += 1 # Double count if move fails

        except (subprocess.SubprocessError, OSError) as e:
            print(f"\nError running exiftool for {filepath}: {e}", file=sys.stderr)
            if _move_file_robustly(filepath, non_photos_dir):
                error_count += 1
            else:
                error_count += 1

    print("\nProcessing complete.")

    # --- Handle Backup Files ---
    print("Moving exiftool backup files...")
    originals_moved_count = 0
    original_files = []
    for root, _, files in os.walk("."):
        if Path(root).resolve() in special_dirs:
            continue
        for name in files:
            if name.endswith("_original"):
                original_files.append(Path(root) / name)

    for orig_path in original_files:
        new_name = orig_path.name.replace("_original", "")
        if _move_file_robustly(orig_path, originals_dir, new_base_name=new_name):
            originals_moved_count += 1
        else:
            error_count += 1

    print(f"Moved {originals_moved_count} backup files to '{originals_dir.name}'.")

    # --- Summary ---
    print("\n--- Timeshift Summary ---")
    print(f"Files successfully time-shifted: {updated_count}")
    print(f"Files with no date tags to update (moved to '{untagged_photos_dir.name}'): {no_tags_count}")
    print(f"Files with errors (moved to '{non_photos_dir.name}'): {error_count}")
    print(f"Original file backups moved to '{originals_dir.name}': {originals_moved_count}")
    print("'timeshift' command complete.")

from datetime import datetime, timedelta

def _get_exif_tags(filepath, tags):
    """Gets specific EXIF tags from a file and returns them as a dictionary."""
    tag_args = [f"-{tag}" for tag in tags]
    try:
        result = subprocess.run(
            ["exiftool", "-s3", "-q"] + tag_args + [str(filepath)],
            capture_output=True, text=True, check=False
        )
        if result.returncode != 0:
            return None

        tag_values = result.stdout.strip().split("\n")
        return dict(zip(tags, tag_values))
    except (subprocess.SubprocessError, OSError):
        return None

def _parse_exif_datetime(dt_str):
    """Parses EXIF's 'YYYY:MM:DD HH:MM:SS' format."""
    try:
        return datetime.strptime(dt_str, "%Y:%m:%d %H:%M:%S")
    except (ValueError, TypeError):
        return None

def handle_pair_jpegs(args, config):
    """
    Identifies RAW+JPEG pairs and moves the JPEG to a separate directory.
    """
    print("Running 'pair-jpegs' command...")

    # --- Setup ---
    extra_jpgs_dir = Path.cwd() / "_extra_jpgs"
    extra_jpgs_dir.mkdir(exist_ok=True)

    raw_ext = tuple(f".{ext}" for ext in config["file_formats"]["raw"])
    img_ext = tuple(f".{ext}" for ext in config["file_formats"]["image"] if ext.startswith("jp"))

    # --- File Discovery ---
    raw_files = []
    for root, _, files in os.walk("."):
        if Path(root).resolve() == extra_jpgs_dir.resolve():
            continue
        for name in files:
            if name.lower().endswith(raw_ext):
                raw_files.append(Path(root) / name)

    print(f"Found {len(raw_files)} RAW files to check for pairs.")

    # --- Main Processing Loop ---
    pairs_found_by_name = 0
    pairs_verified = 0
    jpgs_moved = 0

    for raw_path in raw_files:
        raw_stem = raw_path.stem
        for ext in img_ext:
            jpg_path = raw_path.with_name(f"{raw_stem}{ext}")
            if jpg_path.exists():
                pairs_found_by_name += 1

                # --- Verification ---
                tags_to_check = ["CameraModelName", "DateTimeOriginal"]
                raw_tags = _get_exif_tags(raw_path, tags_to_check)
                jpg_tags = _get_exif_tags(jpg_path, tags_to_check)

                if not raw_tags or not jpg_tags:
                    continue

                raw_dt = _parse_exif_datetime(raw_tags.get("DateTimeOriginal"))
                jpg_dt = _parse_exif_datetime(jpg_tags.get("DateTimeOriginal"))

                if not raw_dt or not jpg_dt:
                    continue

                model_match = raw_tags.get("CameraModelName") == jpg_tags.get("CameraModelName")
                time_match = abs(raw_dt - jpg_dt) <= timedelta(seconds=1)

                if model_match and time_match:
                    pairs_verified += 1
                    if _move_file_robustly(jpg_path, extra_jpgs_dir):
                        jpgs_moved += 1

                # Stop checking other jpg extensions for this raw file
                break

    print("\n--- Pair JPEGs Summary ---")
    print(f"Potential pairs found by name: {pairs_found_by_name}")
    print(f"Pairs verified by EXIF data: {pairs_verified}")
    print(f"Verified JPEGs moved to '{extra_jpgs_dir.name}': {jpgs_moved}")
    print("'pair-jpegs' command complete.")


def handle_by_date(args, config):
    """
    Organizes files into a 'by-date/YYYY-MM-DD/' directory structure.
    """
    print("Running 'by-date' command...")

    # --- Setup ---
    src_dir = Path.cwd() / "src"
    by_date_dir = Path.cwd() / "by-date"
    workspace_dir = Path.cwd() / config["workspace_dir"]

    src_dir.mkdir(exist_ok=True)
    by_date_dir.mkdir(exist_ok=True)

    # --- Step 0: Move files to 'src' ---
    print(f"Moving items to temporary '{src_dir.name}' directory...")
    moved_to_src_count = 0
    items_in_cwd = list(Path.cwd().iterdir())

    # Define exclusions
    # Note: comparing resolved paths is more robust
    exclude_dirs = {src_dir.resolve(), by_date_dir.resolve(), workspace_dir.resolve()}
    for d in Path.cwd().glob("_*"): # Exclude all dirs starting with _
        exclude_dirs.add(d.resolve())

    for item_path in items_in_cwd:
        if item_path.resolve() in exclude_dirs or item_path.name == "photoflow.py":
            continue
        try:
            shutil.move(str(item_path), src_dir)
            moved_to_src_count += 1
        except shutil.Error as e:
            print(f"Warning: Could not move {item_path.name}: {e}", file=sys.stderr)

    print(f"Moved {moved_to_src_count} items to '{src_dir.name}'.")

    # --- Step 1: Rename files from 'src' into 'by-date' (flat) ---
    print("Step 1: Renaming and moving files to 'by-date' based on EXIF date...")
    if not any(src_dir.iterdir()):
        print("Source directory is empty. Nothing to process.")
    else:
        try:
            # Format: 'YYYY-MM-DD--HH-MM-SS-copynumber.ext'
            # The # in DateTimeOriginal# ensures that if the original date is invalid, nothing is written.
            filename_format = f"-FileName<{by_date_dir.name}/%Y-%m-%d--%H-%M-%S%%-c.%%le"
            date_format = "%Y:%m:%d %H:%M:%S" # This is what exiftool reads from the tag

            subprocess.run(
                [
                    "exiftool",
                    "-overwrite_original",
                    "-P", # Preserve filesystem modification time
                    "-r", # Recurse
                    f"-d", date_format,
                    filename_format,
                    str(src_dir)
                ],
                capture_output=True, text=True, check=False
            )
        except (subprocess.SubprocessError, OSError) as e:
            print(f"Error during Step 1 (rename): {e}", file=sys.stderr)

    # --- Step 2: Move files into daily subfolders ---
    print("Step 2: Moving files into daily subfolders...")
    if not any(by_date_dir.glob("*.*")): # Check if there are any files to process
         print("No files to organize into daily subfolders.")
    else:
        try:
            # Moves files into a directory like 'by-date/2023-10-27'
            directory_format = f"-Directory<{by_date_dir.name}/%Y-%m-%d"
            subprocess.run(
                [
                    "exiftool",
                    "-overwrite_original",
                    "-P",
                    "-r",
                    "-d", "%Y:%m:%d %H:%M:%S", # Match the tag's format
                    directory_format,
                    str(by_date_dir)
                ],
                capture_output=True, text=True, check=False
            )
        except (subprocess.SubprocessError, OSError) as e:
            print(f"Error during Step 2 (move to subfolders): {e}", file=sys.stderr)

    # --- Step 3: Cleanup and Reporting ---
    print("Step 3: Cleaning up...")
    remaining_files = list(src_dir.rglob("*"))
    if remaining_files:
        print(f"Warning: {len(remaining_files)} items remain in '{src_dir.name}'. These may lack date tags or have caused errors.")
        # Optionally log these files to a report
    else:
        try:
            shutil.rmtree(src_dir)
            print(f"Removed empty source directory: '{src_dir.name}'")
        except OSError as e:
            print(f"Warning: Could not remove source directory {src_dir.name}: {e}", file=sys.stderr)

    print("'by-date' command complete.")


def handle_geotag(args, config):
    """
    Applies GPS data to files from GPX tracks with overwrite protection.
    """
    print("Running 'geotag' command...")

    # --- Argument Validation ---
    gpx_dir = Path(args.gpx_dir)
    if not gpx_dir.is_dir():
        print(f"Error: GPX directory not found at '{gpx_dir}'", file=sys.stderr)
        return 1

    tz_pattern = re.compile(r"^[+-]\d{2}:\d{2}$")
    if not tz_pattern.match(args.timezone):
        print(f"Error: Invalid timezone format: '{args.timezone}'. Expected format like '+02:00' or '-05:00'.", file=sys.stderr)
        return 1

    # --- Setup ---
    target_dir = Path.cwd() / "by-date"
    if not target_dir.is_dir():
        print(f"Error: Target directory '{target_dir.name}' not found. Please run 'by-date' first.", file=sys.stderr)
        return 1

    temp_hold_dir = Path.cwd() / "_already_geotagged"
    temp_hold_dir.mkdir(exist_ok=True)

    # --- Stage 1: Segregate Already-Tagged Files ---
    print("Scanning for files that are already geotagged...")
    files_to_process = list(target_dir.rglob("*.*"))
    already_tagged_count = 0

    for i, filepath in enumerate(files_to_process):
        print(f"\rScanning {i+1}/{len(files_to_process)}: {filepath.name}", end="", flush=True)
        if not filepath.is_file():
            continue

        # Use exiftool to check for the presence of GPSLatitude.
        result = subprocess.run(
            ["exiftool", "-if", "$GPSLatitude", "-p", "$GPSLatitude", str(filepath)],
            capture_output=True, text=True, check=False
        )

        # If the output is not empty, the tag exists.
        if result.stdout.strip():
            # Move the file to the holding directory, preserving structure.
            relative_path = filepath.relative_to(target_dir)
            hold_path_dir = temp_hold_dir / relative_path.parent
            hold_path_dir.mkdir(parents=True, exist_ok=True)
            try:
                shutil.move(str(filepath), hold_path_dir)
                already_tagged_count += 1
            except shutil.Error as e:
                print(f"\nWarning: Could not move already-tagged file {filepath.name}: {e}", file=sys.stderr)

    print(f"\nFound and moved {already_tagged_count} already geotagged files to a temporary location.")

    # --- Stage 2: Geotag Remaining Files ---
    print(f"Geotagging remaining files in '{target_dir.name}'...")

    # Construct exiftool command
    geotime_arg = f"-geotime<${{DateTimeOriginal}}{args.timezone}"
    gpx_pattern = str(gpx_dir.resolve() / "*.gpx")

    try:
        result = subprocess.run(
            [
                "exiftool",
                "-overwrite_original",
                "-P",
                geotime_arg,
                "-geotag", gpx_pattern,
                "-r",
                str(target_dir)
            ],
            capture_output=True, text=True, check=False
        )
        # Simple parsing of exiftool's summary
        updated_summary = re.search(r"(\d+) image files updated", result.stdout)
        updated_count = int(updated_summary.group(1)) if updated_summary else 0
        print(f"Exiftool updated {updated_count} files.")
        if result.stderr:
            print("Exiftool reported errors:", file=sys.stderr)
            print(result.stderr, file=sys.stderr)

    except (subprocess.SubprocessError, OSError, FileNotFoundError) as e:
        print(f"FATAL: An error occurred while running exiftool: {e}", file=sys.stderr)
        updated_count = 0


    # --- Stage 3: Restore Already-Tagged Files ---
    print("Restoring already-geotagged files...")
    restored_count = 0
    if already_tagged_count > 0:
        for item in temp_hold_dir.rglob("*"):
            relative_path = item.relative_to(temp_hold_dir)
            dest_path = target_dir / relative_path

            if item.is_file():
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                try:
                    shutil.move(str(item), dest_path)
                    restored_count += 1
                except shutil.Error as e:
                    print(f"Warning: Could not restore file {item.name}: {e}", file=sys.stderr)

    try:
        shutil.rmtree(temp_hold_dir)
    except OSError as e:
        print(f"Warning: Could not remove temporary directory {temp_hold_dir.name}: {e}", file=sys.stderr)

    # --- Summary ---
    print("\n--- Geotag Summary ---")
    print(f"Files skipped (already had GPS data): {already_tagged_count}")
    print(f"Files successfully geotagged in this run: {updated_count}")
    print(f"Restored {restored_count} previously tagged files.")
    print("'geotag' command complete.")


def handle_to_develop(args, config):
    """
    Identifies folders that require further processing steps in a RAW development workflow.
    """
    print("Running 'to-develop' command...")

    # --- Setup ---
    raw_exts = [f".{ext}" for ext in config["file_formats"]["raw"]]
    tif_exts = [".tif", ".tiff"]

    # --- Stage 1: Find folders with RAWs missing TIFs ---
    print("Stage 1: Checking for RAW files missing TIF counterparts...")
    folders_missing_tifs = set()
    all_raw_files = []
    for ext in raw_exts:
        all_raw_files.extend(Path.cwd().rglob(f"*{ext}"))

    for raw_path in all_raw_files:
        raw_stem = raw_path.stem
        raw_dir = raw_path.parent

        # Search for a TIF with the same stem in the raw_dir or any of its subdirectories
        tif_found = False
        for tif_ext in tif_exts:
            if any(raw_dir.rglob(f"{raw_stem}{tif_ext}")):
                tif_found = True
                break

        if not tif_found:
            folders_missing_tifs.add(raw_dir)

    print(f"Found {len(folders_missing_tifs)} folders with RAW files needing TIF generation.")

    # --- Stage 2: Find folders with TIFs missing Standard JPEGs ---
    print("Stage 2: Checking for TIF files missing Standard JPG counterparts...")
    folders_missing_std_jpgs = set()
    all_tif_files = []
    for ext in tif_exts:
        all_tif_files.extend(Path.cwd().rglob(f"*{ext}"))

    for tif_path in all_tif_files:
        tif_stem = tif_path.stem
        tif_dir = tif_path.parent
        parent_of_tif_dir = tif_dir.parent

        # The expected JPEG is in the parent directory of the TIF's directory
        expected_jpg_name = f"{tif_stem}__std.jpg"
        expected_jpg_path = parent_of_tif_dir / expected_jpg_name

        if not expected_jpg_path.exists():
            folders_missing_std_jpgs.add(tif_dir)

    print(f"Found {len(folders_missing_std_jpgs)} folders with TIF files needing Standard JPG generation.")

    # --- Final Report ---
    print("\n--- To-Develop Summary ---")

    if folders_missing_tifs:
        print("\nFolders needing TIF/TIFF generation (SRW found, TIF/TIFF missing):")
        for folder in sorted(list(folders_missing_tifs)):
            print(f"  {folder}")
    else:
        print("\nNo folders found needing TIF/TIFF generation.")

    if folders_missing_std_jpgs:
        print("\nFolders needing Standard JPG generation (TIF/TIFF found, *__std.jpg missing):")
        for folder in sorted(list(folders_missing_std_jpgs)):
            print(f"  {folder}")
    else:
        print("\nNo folders found needing Standard JPG generation.")

    print("\n'to-develop' command complete.")


# --- Main Entry Point ---

def main():
    """Main entry point for the script."""

    # Load configuration
    config = load_or_create_config()

    # --- Main Parser Setup ---
    parser = argparse.ArgumentParser(
        description=(
            "A tool for managing and processing photo and video collections.\n\n"
            "The workflow is broken down into numbered phases (subcommands).\n"
            "It is recommended to run them in order for a complete workflow, e.g.:\n"
            "  1. 01-dedup         (Find and report duplicates)\n"
            "  2. 02-timeshift     (Correct camera timestamps if needed)\n"
            "  3. 03-pair-jpegs    (Separate RAW+JPEG pairs)\n"
            "  4. 04-by-date       (Organize files into date-based folders)\n"
            "  5. 05-geotag        (Add GPS data from GPX tracks)\n"
            "  6. 06-to-develop    (Report on files needing development, e.g. RAW->TIF)"
        ),
        epilog="Use 'photoflow.py <command> --help' for more information on a specific command.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    subparsers = parser.add_subparsers(dest="command", required=True, help="Available commands (phases)")

    # --- 01-dedup ---
    parser_dedup = subparsers.add_parser(
        "01-dedup",
        help="Phase 1: Finds duplicate files and files with naming conflicts."
    )
    parser_dedup.set_defaults(func=handle_dedup)

    # --- 02-timeshift ---
    parser_timeshift = subparsers.add_parser(
        "02-timeshift",
        help="Phase 2: Shifts EXIF timestamps for a batch of files."
    )
    parser_timeshift.add_argument(
        "--offset",
        required=True,
        help="The time shift specification string (e.g., '+=1:30:0')."
    )
    parser_timeshift.set_defaults(func=handle_timeshift)

    # --- 03-pair-jpegs ---
    parser_pair_jpegs = subparsers.add_parser(
        "03-pair-jpegs",
        help="Phase 3: Identifies RAW+JPEG pairs and separates the JPEG file."
    )
    parser_pair_jpegs.set_defaults(func=handle_pair_jpegs)

    # --- 04-by-date ---
    parser_by_date = subparsers.add_parser(
        "04-by-date",
        help="Phase 4: Organizes files into a YYYY-MM-DD directory structure."
    )
    parser_by_date.set_defaults(func=handle_by_date)

    # --- 05-geotag ---
    parser_geotag = subparsers.add_parser(
        "05-geotag",
        help="Phase 5: Applies GPS data to files from GPX tracks."
    )
    parser_geotag.add_argument(
        "--gpx-dir",
        required=True,
        help="Path to the directory containing GPX files."
    )
    parser_geotag.add_argument(
        "--timezone",
        required=True,
        help="Timezone offset for DateTimeOriginal (e.g., '+02:00' or '-05:00')."
    )
    parser_geotag.set_defaults(func=handle_geotag)

    # --- 06-to-develop ---
    parser_to_develop = subparsers.add_parser(
        "06-to-develop",
        help="Phase 6: Identifies folders that require further processing steps."
    )
    parser_to_develop.set_defaults(func=handle_to_develop)

    # --- Parse Arguments and Execute ---
    args = parser.parse_args()
    args.func(args, config)

    return 0

if __name__ == '__main__':
    sys.exit(main())
