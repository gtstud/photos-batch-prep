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
import logging
import hashlib
from collections import defaultdict
import re
import subprocess
import shutil
from datetime import datetime, timedelta
from tqdm import tqdm

# --- Global Logger ---
logger = logging.getLogger(__name__)

# --- Configuration Management ---

CONFIG_DIR_NAME = "photoflow"
CONFIG_FILE_NAME = "config.json"

def get_config_path() -> Path:
    """Returns the platform-specific path to the configuration file."""
    config_home = os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")
    return Path(config_home) / CONFIG_DIR_NAME / CONFIG_FILE_NAME

def get_default_config() -> dict:
    """Returns the default configuration dictionary."""
    return {
        "workspace_dir": "_photo_workspace",
        "duplicates_trash_dir": "_duplicates_trash",
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
        logger.info(f"Configuration file not found. Creating a default one at: {config_path}")
        try:
            config_path.parent.mkdir(parents=True, exist_ok=True)
            default_config = get_default_config()
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(default_config, f, indent=2)
            return default_config
        except IOError as e:
            logger.error(f"Could not create configuration file: {e}")
            sys.exit(1)

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logger.error(f"Could not read or parse configuration file at {config_path}: {e}")
        logger.error("Please fix or delete the file to allow recreation.")
        sys.exit(1)

# --- Subcommand Functions ---

def _get_file_hash(filepath, algorithm):
    """Calculates the hash of a file."""
    h = hashlib.new(algorithm)
    try:
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(h.block_size * 4096), b""):
                h.update(chunk)
        return h.hexdigest()
    except IOError:
        return None

def handle_dedup(args, config):
    """
    Finds duplicate files and files with naming conflicts.
    """
    logger.info("Running '01-dedup' command...")

    workspace_dir = Path.cwd() / config["workspace_dir"]
    trash_dir = Path.cwd() / config.get("duplicates_trash_dir", "_duplicates_trash")

    workspace_dir.mkdir(exist_ok=True)
    if not args.dry_run:
        trash_dir.mkdir(exist_ok=True)

    logger.info(f"Workspace directory: {workspace_dir}")
    logger.info(f"Trash directory for duplicates: {trash_dir}")

    conflict_report_path = workspace_dir / "p01-dedup-report01-conflicting_versions.txt"

    checksum_algo = config["dedup"]["checksum_algorithm"]
    logger.info(f"Using '{checksum_algo}' checksum algorithm.")

    logger.info("Scanning files and calculating checksums...")
    file_data = []
    files_by_name = defaultdict(list)

    all_files_for_hashing = []
    for root, dirs, files in os.walk("."):
        if str(workspace_dir.resolve()) in str(Path(root).resolve()) or str(trash_dir.resolve()) in str(Path(root).resolve()):
            continue
        for name in files:
            all_files_for_hashing.append(Path(root) / name)

    for filepath in tqdm(all_files_for_hashing, desc="Hashing files"):
        try:
            size = filepath.stat().st_size
            checksum = _get_file_hash(filepath, checksum_algo)
            if checksum:
                file_info = {"path": filepath, "name": filepath.name, "size": size, "checksum": checksum}
                file_data.append(file_info)
                files_by_name[filepath.name].append(file_info)
        except OSError as e:
            logger.warning(f"Could not process file {filepath}: {e}")

    logger.info(f"Processed {len(file_data)} files.")

    files_by_identity = defaultdict(list)
    for info in file_data:
        key = (info["name"], info["size"], info["checksum"])
        files_by_identity[key].append(info)

    duplicates_found = 0
    for key, items in sorted(files_by_identity.items()):
        if len(items) > 1:
            items.sort(key=lambda x: x["path"])
            duplicates = items[1:]
            for dup in duplicates:
                duplicates_found += 1
                logger.info(f"Found duplicate: '{dup['path']}' (original: '{items[0]['path']}')")
                if args.dry_run:
                    logger.info(f"DRY RUN: Would move '{dup['path']}' to '{trash_dir}'")
                else:
                    try:
                        shutil.move(str(dup['path']), trash_dir)
                    except shutil.Error as e:
                        logger.error(f"Could not move duplicate file {dup['path']}: {e}")

    if duplicates_found > 0:
        logger.info(f"Found and moved {duplicates_found} duplicate files to trash directory: {trash_dir}")
    else:
        logger.info("No duplicate files found.")

    conflicts_found = 0
    with open(conflict_report_path, "w", encoding="utf-8") as f:
        f.write("# Report on files with the same name but different checksums.\n\n")

        for name, items in sorted(files_by_name.items()):
            unique_checksums = {item["checksum"] for item in items}
            if len(unique_checksums) > 1:
                conflicts_found += 1
                f.write(f"Filename: '{name}' has {len(items)} instances with {len(unique_checksums)} different versions:\n")
                for item in sorted(items, key=lambda x: x["checksum"]):
                    f.write(f"  - Checksum: {item['checksum']}, Size: {item['size']}, Path: '{item['path']}'\n")
                f.write("\n")

    if conflicts_found > 0:
        logger.info(f"Found {conflicts_found} files with conflicting versions. Report written to: {conflict_report_path}")
    else:
        logger.info("No conflicting file versions found.")
        if not args.dry_run:
            conflict_report_path.unlink()

    logger.info("'01-dedup' command complete.")


def _move_file_robustly(source_path: Path, target_dir: Path, dry_run: bool, new_base_name: str = None):
    """Moves a file, handling name collisions by adding a counter."""
    if not source_path.exists():
        return None

    base_name = new_base_name if new_base_name else source_path.name
    destination_path = target_dir / base_name

    if dry_run:
        logger.info(f"DRY RUN: Would move '{source_path}' to '{destination_path}'")
        return destination_path

    counter = 0
    while destination_path.exists():
        counter += 1
        extension = "".join(Path(base_name).suffixes)
        stem = base_name.replace(extension, "")
        new_filename = f"{stem}-{counter:02d}{extension}"
        destination_path = target_dir / new_filename

    try:
        shutil.move(source_path, destination_path)
        return destination_path
    except OSError as e:
        logger.error(f"Error moving file {source_path} to {destination_path}: {e}")
        return None

def handle_timeshift(args, config):
    """
    Shifts EXIF date/time tags in files using exiftool.
    """
    logger.info("Running '02-timeshift' command...")

    offset_pattern = re.compile(r"^[+-]?=\d{1,}:\d{1,}:\d{1,}( \d{1,}:\d{1,}:\d{1,})?$")
    if not offset_pattern.match(args.offset):
        logger.error(f"Invalid offset format: '{args.offset}'. Expected format like '+=Y:M:D H:M:S'.")
        return 1

    workspace_dir = Path.cwd() / config["workspace_dir"]
    non_photos_dir = Path.cwd() / "_non_photos"
    untagged_photos_dir = Path.cwd() / "_untagged_photos"
    originals_dir = Path.cwd() / "_originals"

    if not args.dry_run:
        workspace_dir.mkdir(exist_ok=True)
        non_photos_dir.mkdir(exist_ok=True)
        untagged_photos_dir.mkdir(exist_ok=True)
        originals_dir.mkdir(exist_ok=True)

    special_dirs = {workspace_dir.resolve(), non_photos_dir.resolve(), untagged_photos_dir.resolve(), originals_dir.resolve()}

    files_to_process = []
    for root, _, files in os.walk("."):
        if Path(root).resolve() in special_dirs:
            continue
        for name in files:
            if not name.endswith(("_original", ".tmp")):
                files_to_process.append(Path(root) / name)

    logger.info(f"Found {len(files_to_process)} files to process.")

    updated_count, no_tags_count, error_count = 0, 0, 0
    exiftool_cmd = f"-AllDates{args.offset}"

    for filepath in tqdm(files_to_process, desc="Shifting timestamps"):
        if args.dry_run:
            logger.info(f"DRY RUN: Would run exiftool on '{filepath}' with offset '{args.offset}'")
            continue
        try:
            result = subprocess.run(
                ["exiftool", "-m", exiftool_cmd, str(filepath)],
                capture_output=True, text=True, check=False
            )
            logger.debug(f"Exiftool output for {filepath.name}:\n{result.stdout}\n{result.stderr}")

            if "1 image files updated" in result.stdout:
                updated_count += 1
            elif "0 image files updated" in result.stdout:
                if _move_file_robustly(filepath, untagged_photos_dir, args.dry_run):
                    no_tags_count += 1
                else:
                    error_count += 1
            else:
                if _move_file_robustly(filepath, non_photos_dir, args.dry_run):
                    error_count += 1
                else:
                    error_count += 1
        except (subprocess.SubprocessError, OSError) as e:
            logger.error(f"Error running exiftool for {filepath}: {e}")
            if _move_file_robustly(filepath, non_photos_dir, args.dry_run):
                error_count += 1

    logger.info("Moving exiftool backup files...")
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
        if _move_file_robustly(orig_path, originals_dir, args.dry_run, new_base_name=new_name):
            originals_moved_count += 1
        else:
            error_count += 1

    logger.info(f"Moved {originals_moved_count} backup files to '{originals_dir.name}'.")

    logger.info("\n--- Timeshift Summary ---")
    logger.info(f"Files successfully time-shifted: {updated_count}")
    logger.info(f"Files with no date tags to update (moved to '{untagged_photos_dir.name}'): {no_tags_count}")
    logger.info(f"Files with errors (moved to '{non_photos_dir.name}'): {error_count}")
    logger.info(f"Original file backups moved to '{originals_dir.name}': {originals_moved_count}")
    logger.info("'02-timeshift' command complete.")

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
    logger.info("Running '03-pair-jpegs' command...")

    extra_jpgs_dir = Path.cwd() / "_extra_jpgs"
    if not args.dry_run:
        extra_jpgs_dir.mkdir(exist_ok=True)

    raw_ext = tuple(f".{ext}" for ext in config["file_formats"]["raw"])
    img_ext = tuple(f".{ext}" for ext in config["file_formats"]["image"] if ext.startswith("jp"))

    raw_files = []
    for root, _, files in os.walk("."):
        if Path(root).resolve() == extra_jpgs_dir.resolve():
            continue
        for name in files:
            if name.lower().endswith(raw_ext):
                raw_files.append(Path(root) / name)

    logger.info(f"Found {len(raw_files)} RAW files to check for pairs.")

    pairs_found_by_name, pairs_verified, jpgs_moved = 0, 0, 0

    for raw_path in tqdm(raw_files, desc="Pairing JPEGs"):
        raw_stem = raw_path.stem
        for ext in img_ext:
            jpg_path = raw_path.with_name(f"{raw_stem}{ext}")
            if jpg_path.exists():
                pairs_found_by_name += 1

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
                    if _move_file_robustly(jpg_path, extra_jpgs_dir, args.dry_run):
                        jpgs_moved += 1

                break

    logger.info("\n--- Pair JPEGs Summary ---")
    logger.info(f"Potential pairs found by name: {pairs_found_by_name}")
    logger.info(f"Pairs verified by EXIF data: {pairs_verified}")
    logger.info(f"Verified JPEGs moved to '{extra_jpgs_dir.name}': {jpgs_moved}")
    logger.info("'03-pair-jpegs' command complete.")


def handle_by_date(args, config):
    """
    Organizes files into a 'by-date/YYYY-MM-DD/' directory structure.
    """
    logger.info("Running '04-by-date' command...")

    src_dir = Path.cwd() / "src"
    by_date_dir = Path.cwd() / "by-date"
    workspace_dir = Path.cwd() / config["workspace_dir"]

    if not args.dry_run:
        src_dir.mkdir(exist_ok=True)
        by_date_dir.mkdir(exist_ok=True)

    logger.info(f"Moving items to temporary '{src_dir.name}' directory...")
    moved_to_src_count = 0
    items_in_cwd = list(Path.cwd().iterdir())

    exclude_dirs = {src_dir.resolve(), by_date_dir.resolve(), workspace_dir.resolve()}
    for d in Path.cwd().glob("_*"):
        exclude_dirs.add(d.resolve())

    for item_path in items_in_cwd:
        if item_path.resolve() in exclude_dirs or item_path.name == "photoflow.py" or item_path.name == "pyproject.toml":
            continue
        moved_to_src_count += 1
        if args.dry_run:
            logger.info(f"DRY RUN: Would move '{item_path}' to '{src_dir}'")
        else:
            try:
                shutil.move(str(item_path), src_dir)
            except shutil.Error as e:
                logger.warning(f"Could not move {item_path.name}: {e}")

    logger.info(f"Moved {moved_to_src_count} items to '{src_dir.name}'.")

    logger.info("Step 1: Renaming and moving files to 'by-date' based on EXIF date...")
    if not any(src_dir.iterdir()):
        logger.info("Source directory is empty. Nothing to process.")
    elif args.dry_run:
        logger.info("DRY RUN: Would run exiftool to rename and move files from 'src' to 'by-date'.")
    else:
        try:
            filename_format = f"-FileName<{by_date_dir.name}" "/${DateTimeOriginal}"
            date_format = "%Y-%m-%d--%H-%M-%S%%-c.%%le"
            subprocess.run(
                ["exiftool", "-overwrite_original", "-P", "-r", "-d", date_format, filename_format, str(src_dir)],
                capture_output=True, text=True, check=False
            )
        except (subprocess.SubprocessError, OSError) as e:
            logger.error(f"Error during Step 1 (rename): {e}")

    logger.info("Step 2: Moving files into daily subfolders...")
    if not any(by_date_dir.glob("*.*")):
        logger.info("No files to organize into daily subfolders.")
    elif args.dry_run:
        logger.info("DRY RUN: Would run exiftool to move files into daily subfolders.")
    else:
        try:
            directory_format = f"-Directory<{by_date_dir.name}" "/${DateTimeOriginal}"
            date_format = "%Y-%m-%d"
            subprocess.run(
                ["exiftool", "-overwrite_original", "-P", "-r", "-d", date_format, directory_format, str(by_date_dir)],
                capture_output=True, text=True, check=False
            )
        except (subprocess.SubprocessError, OSError) as e:
            logger.error(f"Error during Step 2 (move to subfolders): {e}")

    logger.info("Step 3: Cleaning up...")
    remaining_files = list(src_dir.rglob("*")) if src_dir.exists() else []
    if remaining_files:
        logger.warning(f"{len(remaining_files)} items remain in '{src_dir.name}'. These may lack date tags or have caused errors.")
    elif src_dir.exists():
        if args.dry_run:
            logger.info(f"DRY RUN: Would remove empty source directory: '{src_dir.name}'")
        else:
            try:
                shutil.rmtree(src_dir)
                logger.info(f"Removed empty source directory: '{src_dir.name}'")
            except OSError as e:
                logger.warning(f"Could not remove source directory {src_dir.name}: {e}")

    logger.info("'04-by-date' command complete.")


def handle_geotag(args, config):
    """
    Applies GPS data to files from GPX tracks with overwrite protection.
    """
    logger.info("Running '05-geotag' command...")

    gpx_dir = Path(args.gpx_dir)
    if not gpx_dir.is_dir():
        logger.error(f"GPX directory not found at '{gpx_dir}'")
        return 1

    tz_pattern = re.compile(r"^[+-]\d{2}:\d{2}$")
    if not tz_pattern.match(args.timezone):
        logger.error(f"Invalid timezone format: '{args.timezone}'. Expected format like '+02:00' or '-05:00'.")
        return 1

    target_dir = Path.cwd() / "by-date"
    if not target_dir.is_dir():
        logger.error(f"Target directory '{target_dir.name}' not found. Please run '04-by-date' first.")
        return 1

    temp_hold_dir = Path.cwd() / "_already_geotagged"
    if not args.dry_run:
        temp_hold_dir.mkdir(exist_ok=True)

    logger.info("Scanning for files that are already geotagged...")
    files_to_process = list(target_dir.rglob("*.*"))
    already_tagged_count = 0

    for filepath in tqdm(files_to_process, desc="Checking for existing GPS"):
        if not filepath.is_file():
            continue

        result = subprocess.run(
            ["exiftool", "-if", "$GPSLatitude", "-p", "$GPSLatitude", str(filepath)],
            capture_output=True, text=True, check=False
        )

        if result.stdout.strip():
            already_tagged_count += 1
            if args.dry_run:
                logger.info(f"DRY RUN: Would move already-tagged file '{filepath}' to holding area.")
            else:
                relative_path = filepath.relative_to(target_dir)
                hold_path_dir = temp_hold_dir / relative_path.parent
                hold_path_dir.mkdir(parents=True, exist_ok=True)
                try:
                    shutil.move(str(filepath), hold_path_dir)
                except shutil.Error as e:
                    logger.warning(f"Could not move already-tagged file {filepath.name}: {e}")

    logger.info(f"Found and moved {already_tagged_count} already geotagged files to a temporary location.")

    logger.info(f"Geotagging remaining files in '{target_dir.name}'...")

    geotime_arg = f"-geotime<${{DateTimeOriginal}}{args.timezone}"
    gpx_pattern = str(gpx_dir.resolve() / "*.gpx")

    updated_count = 0
    if args.dry_run:
        logger.info(f"DRY RUN: Would run exiftool geotag with pattern '{gpx_pattern}' on '{target_dir}'.")
    else:
        try:
            result = subprocess.run(
                ["exiftool", "-overwrite_original", "-P", geotime_arg, "-geotag", gpx_pattern, "-r", str(target_dir)],
                capture_output=True, text=True, check=False
            )
            updated_summary = re.search(r"(\d+) image files updated", result.stdout)
            updated_count = int(updated_summary.group(1)) if updated_summary else 0
            logger.info(f"Exiftool updated {updated_count} files.")
            if result.stderr:
                logger.warning(f"Exiftool reported errors:\n{result.stderr}")

        except (subprocess.SubprocessError, OSError, FileNotFoundError) as e:
            logger.error(f"FATAL: An error occurred while running exiftool: {e}")

    logger.info("Restoring already-geotagged files...")
    restored_count = 0
    if already_tagged_count > 0:
        items_to_restore = list(temp_hold_dir.rglob("*"))
        for item in tqdm(items_to_restore, desc="Restoring files"):
            relative_path = item.relative_to(temp_hold_dir)
            dest_path = target_dir / relative_path

            if item.is_file():
                restored_count += 1
                if args.dry_run:
                    logger.info(f"DRY RUN: Would restore '{item}' to '{dest_path}'.")
                else:
                    dest_path.parent.mkdir(parents=True, exist_ok=True)
                    try:
                        shutil.move(str(item), dest_path)
                    except shutil.Error as e:
                        logger.warning(f"Could not restore file {item.name}: {e}")

    if not args.dry_run:
        try:
            shutil.rmtree(temp_hold_dir)
        except OSError as e:
            logger.warning(f"Could not remove temporary directory {temp_hold_dir.name}: {e}")

    logger.info("\n--- Geotag Summary ---")
    logger.info(f"Files skipped (already had GPS data): {already_tagged_count}")
    logger.info(f"Files successfully geotagged in this run: {updated_count}")
    logger.info(f"Restored {restored_count} previously tagged files.")
    logger.info("'05-geotag' command complete.")


def handle_to_develop(args, config):
    """
    Identifies folders that require further processing steps in a RAW development workflow.
    """
    logger.info("Running '06-to-develop' command...")

    raw_exts = [f".{ext}" for ext in config["file_formats"]["raw"]]
    tif_exts = [".tif", ".tiff"]

    logger.info("Stage 1: Checking for RAW files missing TIF counterparts...")
    folders_missing_tifs = set()
    all_raw_files = []
    for ext in raw_exts:
        all_raw_files.extend(Path.cwd().rglob(f"*{ext}"))

    for raw_path in tqdm(all_raw_files, desc="Checking RAW->TIF"):
        raw_stem = raw_path.stem
        raw_dir = raw_path.parent

        tif_found = False
        for tif_ext in tif_exts:
            if any(raw_dir.rglob(f"{raw_stem}{tif_ext}")):
                tif_found = True
                break

        if not tif_found:
            folders_missing_tifs.add(raw_dir)

    logger.info(f"Found {len(folders_missing_tifs)} folders with RAW files needing TIF generation.")

    logger.info("Stage 2: Checking for TIF files missing Standard JPG counterparts...")
    folders_missing_std_jpgs = set()
    all_tif_files = []
    for ext in tif_exts:
        all_tif_files.extend(Path.cwd().rglob(f"*{ext}"))

    for tif_path in tqdm(all_tif_files, desc="Checking TIF->JPG"):
        tif_stem = tif_path.stem
        tif_dir = tif_path.parent
        parent_of_tif_dir = tif_dir.parent

        expected_jpg_name = f"{tif_stem}__std.jpg"
        expected_jpg_path = parent_of_tif_dir / expected_jpg_name

        if not expected_jpg_path.exists():
            folders_missing_std_jpgs.add(tif_dir)

    logger.info(f"Found {len(folders_missing_std_jpgs)} folders with TIF files needing Standard JPG generation.")

    logger.info("\n--- To-Develop Summary ---")

    if folders_missing_tifs:
        logger.info("\nFolders needing TIF/TIFF generation (SRW found, TIF/TIFF missing):")
        for folder in sorted(list(folders_missing_tifs)):
            logger.info(f"  {folder}")
    else:
        logger.info("\nNo folders found needing TIF/TIFF generation.")

    if folders_missing_std_jpgs:
        logger.info("\nFolders needing Standard JPG generation (TIF/TIFF found, *__std.jpg missing):")
        for folder in sorted(list(folders_missing_std_jpgs)):
            logger.info(f"  {folder}")
    else:
        logger.info("\nNo folders found needing Standard JPG generation.")

    logger.info("\n'06-to-develop' command complete.")


# --- Helper Functions for Robustness ---

def check_dependencies():
    """Checks for required command-line tools."""
    if not shutil.which("exiftool"):
        logger.critical("CRITICAL ERROR: 'exiftool' not found in your system's PATH.")
        logger.critical("Please install ExifTool from https://exiftool.org/ and ensure it is accessible.")
        sys.exit(1)
    logger.debug("Dependency check passed: 'exiftool' is available.")

def check_write_permission(directory: Path):
    """Checks if the script has write permissions in a given directory."""
    if not os.access(directory, os.W_OK):
        logger.critical(f"CRITICAL ERROR: No write permissions in directory: {directory}")
        sys.exit(1)
    logger.debug(f"Permission check passed: Write access is available in {directory}.")


# --- Main Entry Point ---

def setup_logging(verbose, workspace_dir):
    """Configures the root logger."""
    level = logging.DEBUG if verbose else logging.INFO

    # Create workspace if it doesn't exist for the error log file
    workspace_dir.mkdir(exist_ok=True)
    error_log_path = workspace_dir / "photoflow-errors.log"

    handlers = [logging.StreamHandler(sys.stdout)]

    # Add a file handler for errors
    file_handler = logging.FileHandler(error_log_path)
    file_handler.setLevel(logging.WARNING)
    file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    handlers.append(file_handler)

    logging.basicConfig(
        level=level,
        format="[%(levelname)s] %(message)s",
        handlers=handlers
    )

def main():
    """Main entry point for the script."""

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
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose debug output.")
    parser.add_argument("--dry-run", action="store_true", help="Simulate actions without making any changes to files.")

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

    # Load configuration first to get workspace path
    config = load_or_create_config()
    workspace_dir = Path.cwd() / config["workspace_dir"]

    # Setup logging
    setup_logging(args.verbose, workspace_dir)

    # Run pre-flight checks
    check_dependencies()
    check_write_permission(Path.cwd())

    # Execute command
    args.func(args, config)

    return 0

if __name__ == '__main__':
    sys.exit(main())
