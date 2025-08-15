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
import exiftool

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
    logger.info("Running '1-dedup' command...")

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

    logger.info("'1-dedup' command complete.")


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
    logger.info("Running '2-timeshift' command...")

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

    try:
        with exiftool.ExifToolHelper() as et:
            for filepath in tqdm(files_to_process, desc="Shifting timestamps"):
                if args.dry_run:
                    logger.info(f"DRY RUN: Would run exiftool on '{filepath}' with offset '{args.offset}'")
                    continue
                try:
                    output = et.execute("-m", exiftool_cmd, str(filepath))
                    logger.debug(f"Exiftool output for {filepath.name}:\n{output}")

                    if "1 image files updated" in output:
                        updated_count += 1
                    elif "0 image files updated" in output:
                        if _move_file_robustly(filepath, untagged_photos_dir, args.dry_run):
                            no_tags_count += 1
                        else:
                            error_count += 1
                    else:
                        if et.last_stderr:
                            logger.warning(f"Exiftool stderr for {filepath.name}: {et.last_stderr}")
                        if _move_file_robustly(filepath, non_photos_dir, args.dry_run):
                            error_count += 1
                        else:
                            error_count += 1
                except Exception as e:
                    logger.error(f"Error processing {filepath} with pyexiftool: {e}")
                    if _move_file_robustly(filepath, non_photos_dir, args.dry_run):
                        error_count += 1
    except Exception as e:
        logger.error(f"Failed to start exiftool. Aborting timeshift. Error: {e}")
        # If we are not in dry_run, all files that were to be processed result in an error.
        if not args.dry_run:
            error_count = len(files_to_process)

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
    logger.info("'2-timeshift' command complete.")

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
    logger.info("Running '3-pair-jpegs' command...")

    extra_jpgs_dir = Path.cwd() / "_extra_jpgs"
    if not args.dry_run:
        extra_jpgs_dir.mkdir(exist_ok=True)

    raw_ext = tuple(f".{ext}" for ext in config["file_formats"]["raw"])
    img_ext = tuple(f".{ext}" for ext in config["file_formats"]["image"] if "jp" in ext)

    raw_files = []
    for root, _, files in os.walk("."):
        if Path(root).resolve() == extra_jpgs_dir.resolve():
            continue
        for name in files:
            if name.lower().endswith(raw_ext):
                raw_files.append(Path(root) / name)

    logger.info(f"Found {len(raw_files)} RAW files to check for pairs.")

    pairs_found_by_name, pairs_verified, jpgs_moved = 0, 0, 0
    tags_to_check = ["EXIF:CameraModelName", "EXIF:DateTimeOriginal"]

    try:
        with exiftool.ExifToolHelper() as et:
            for raw_path in tqdm(raw_files, desc="Pairing JPEGs"):
                raw_stem = raw_path.stem
                for ext in img_ext:
                    jpg_path = raw_path.with_name(f"{raw_stem}{ext}")
                    if jpg_path.exists():
                        pairs_found_by_name += 1

                        try:
                            metadata = et.get_tags([str(raw_path), str(jpg_path)], tags=tags_to_check)
                            if len(metadata) < 2:
                                continue
                            raw_tags, jpg_tags = metadata[0], metadata[1]
                        except Exception as e:
                            logger.warning(f"Could not read EXIF for {raw_path} or {jpg_path}: {e}")
                            continue

                        raw_dt = _parse_exif_datetime(raw_tags.get("EXIF:DateTimeOriginal"))
                        jpg_dt = _parse_exif_datetime(jpg_tags.get("EXIF:DateTimeOriginal"))

                        if not raw_dt or not jpg_dt:
                            continue

                        model_match = raw_tags.get("EXIF:CameraModelName") == jpg_tags.get("EXIF:CameraModelName")
                        time_match = abs(raw_dt - jpg_dt) <= timedelta(seconds=1)

                        if model_match and time_match:
                            pairs_verified += 1
                            if _move_file_robustly(jpg_path, extra_jpgs_dir, args.dry_run):
                                jpgs_moved += 1
                        break  # Found a pair, move to the next RAW file
    except Exception as e:
        logger.error(f"Failed to start exiftool. Aborting pair-jpegs. Error: {e}")


    logger.info("\n--- Pair JPEGs Summary ---")
    logger.info(f"Potential pairs found by name: {pairs_found_by_name}")
    logger.info(f"Pairs verified by EXIF data: {pairs_verified}")
    logger.info(f"Verified JPEGs moved to '{extra_jpgs_dir.name}': {jpgs_moved}")
    logger.info("'3-pair-jpegs' command complete.")


def handle_by_date(args, config):
    """
    Organizes files into a 'by-date/YYYY-MM-DD/' directory structure based on EXIF date.
    This version uses pyexiftool to read data and Python for file operations.
    """
    logger.info("Running '4-by-date' command...")

    by_date_dir = Path.cwd() / "by-date"
    workspace_dir = Path.cwd() / config["workspace_dir"]

    if not args.dry_run:
        by_date_dir.mkdir(exist_ok=True)

    # --- Collect files to process ---
    all_files = [p for p in Path.cwd().rglob("*") if p.is_file()]
    files_to_process = []

    exclude_dirs = {by_date_dir.resolve(), workspace_dir.resolve()}
    for d in Path.cwd().glob("_*"):
        exclude_dirs.add(d.resolve())

    for p in all_files:
        # Exclude files inside excluded directories (e.g. `_photo_workspace`, `by-date`)
        if any(excluded_dir in p.resolve().parents for excluded_dir in exclude_dirs):
            continue
        # Exclude script files in the root directory
        if p.parent.resolve() == Path.cwd().resolve() and p.name in ("photoflow.py", "pyproject.toml", "README.md", "specification.md", ".gitignore"):
            continue
        files_to_process.append(p)

    logger.info(f"Found {len(files_to_process)} files to organize.")
    if not files_to_process:
        logger.info("'4-by-date' command complete. No files to process.")
        return

    # --- Process files ---
    moved_count = 0
    no_date_count = 0

    try:
        with exiftool.ExifToolHelper() as et:
            metadata_list = et.get_tags(
                [str(p) for p in files_to_process],
                tags=["EXIF:DateTimeOriginal"]
            )

            for metadata in tqdm(metadata_list, desc="Organizing by date"):
                source_path_str = metadata.get("SourceFile")
                if not source_path_str:
                    continue
                source_path = Path(source_path_str)

                dt_str = metadata.get("EXIF:DateTimeOriginal")
                dt = _parse_exif_datetime(dt_str)

                if not dt:
                    logger.warning(f"No valid 'DateTimeOriginal' tag for '{source_path}'. Skipping.")
                    no_date_count += 1
                    continue

                day_dir_name = dt.strftime("%Y-%m-%d")
                new_stem = dt.strftime("%Y-%m-%d--%H-%M-%S")
                extension = source_path.suffix.lower()
                new_base_name = f"{new_stem}{extension}"

                dest_dir = by_date_dir / day_dir_name

                if not args.dry_run:
                    dest_dir.mkdir(parents=True, exist_ok=True)

                if _move_file_robustly(source_path, dest_dir, args.dry_run, new_base_name=new_base_name):
                    moved_count +=1
                else:
                    # If move fails, it's an error, but we can just count it as not moved.
                    # _move_file_robustly already logs errors.
                    pass

    except Exception as e:
        logger.error(f"An error occurred during 'by-date' processing: {e}")
        return

    logger.info("\n--- By-Date Summary ---")
    logger.info(f"Files successfully moved and renamed: {moved_count}")
    logger.info(f"Files skipped (no date tag): {no_date_count}")
    logger.info("'4-by-date' command complete.")


def handle_geotag(args, config):
    """
    Applies GPS data to files from GPX tracks, skipping files that are already geotagged.
    """
    logger.info("Running '5-geotag' command...")

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

    all_files = [p for p in target_dir.rglob("*") if p.is_file()]
    logger.info(f"Found {len(all_files)} total files in '{target_dir.name}'.")
    if not all_files:
        logger.info("'5-geotag' command complete.")
        return

    files_to_geotag = []
    already_tagged_count = 0

    logger.info("Checking for existing GPS data...")
    try:
        with exiftool.ExifToolHelper() as et:
            metadata_list = et.get_tags([str(p) for p in all_files], tags=["GPSLatitude"])
            for i, metadata in enumerate(metadata_list):
                if "EXIF:GPSLatitude" in metadata or "Composite:GPSLatitude" in metadata:
                    already_tagged_count += 1
                else:
                    files_to_geotag.append(all_files[i])
    except Exception as e:
        logger.error(f"Failed to read EXIF data with pyexiftool: {e}")
        return

    logger.info(f"Found {already_tagged_count} files that are already geotagged and will be skipped.")

    if not files_to_geotag:
        logger.info("No new files to geotag.")
        updated_count = 0
    elif args.dry_run:
        logger.info(f"DRY RUN: Would attempt to geotag {len(files_to_geotag)} files.")
        updated_count = 0
    else:
        logger.info(f"Attempting to geotag {len(files_to_geotag)} files...")
        geotime_arg = f"-geotime<${{DateTimeOriginal}}{args.timezone}"
        gpx_pattern = str(gpx_dir.resolve() / "*.gpx")
        updated_count = 0

        try:
            with exiftool.ExifToolHelper() as et:
                params = [
                    "-overwrite_original",
                    "-P",
                    geotime_arg,
                    "-geotag",
                    gpx_pattern,
                ]
                files_to_geotag_str = [str(p) for p in files_to_geotag]
                output = et.execute(*params, *files_to_geotag_str)

                updated_summary = re.search(r"(\d+) image files updated", output)
                updated_count = int(updated_summary.group(1)) if updated_summary else 0

                logger.debug(f"Exiftool output:\n{output}")
                if et.last_stderr:
                    logger.warning(f"Exiftool reported errors:\n{et.last_stderr}")
        except Exception as e:
            logger.error(f"An error occurred while running exiftool for geotagging: {e}")

    logger.info("\n--- Geotag Summary ---")
    logger.info(f"Files skipped (already had GPS data): {already_tagged_count}")
    logger.info(f"Files successfully geotagged in this run: {updated_count}")
    logger.info("'5-geotag' command complete.")


def handle_to_develop(args, config):
    """
    Identifies folders that require further processing steps in a RAW development workflow.
    """
    logger.info("Running '6-to-develop' command...")

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

    logger.info("\n'6-to-develop' command complete.")


# --- Helper Functions for Robustness ---

def check_dependencies():
    """Checks that the exiftool command-line tool is available."""
    try:
        with exiftool.ExifTool() as et:
            # Check if exiftool is running by getting its version
            version = et.version
            logger.debug(f"Dependency check passed: found exiftool version {version}.")
    except FileNotFoundError:
        logger.critical("CRITICAL ERROR: 'exiftool' command not found.")
        logger.critical(
            "Please install ExifTool from https://exiftool.org/ and ensure it is in your system's PATH."
        )
        sys.exit(1)
    except Exception as e:
        logger.critical(f"CRITICAL ERROR: An unexpected error occurred while checking for exiftool: {e}")
        sys.exit(1)

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
            "  1. 1-dedup         (Find and report duplicates)\n"
            "  2. 2-timeshift     (Correct camera timestamps if needed)\n"
            "  3. 3-pair-jpegs    (Separate RAW+JPEG pairs)\n"
            "  4. 4-by-date       (Organize files into date-based folders)\n"
            "  5. 5-geotag        (Add GPS data from GPX tracks)\n"
            "  6. 6-to-develop    (Report on files needing development, e.g. RAW->TIF)"
        ),
        epilog="Use 'photoflow.py <command> --help' for more information on a specific command.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose debug output.")
    parser.add_argument("--dry-run", action="store_true", help="Simulate actions without making any changes to files.")

    subparsers = parser.add_subparsers(dest="command", required=True, help="Available commands (phases)")

    # --- 1-dedup ---
    parser_dedup = subparsers.add_parser(
        "1-dedup",
        help="Phase 1: Finds duplicate files and files with naming conflicts."
    )
    parser_dedup.set_defaults(func=handle_dedup)

    # --- 2-timeshift ---
    parser_timeshift = subparsers.add_parser(
        "2-timeshift",
        help="Phase 2: Shifts EXIF timestamps for a batch of files."
    )
    parser_timeshift.add_argument(
        "--offset",
        required=True,
        help="The time shift specification string (e.g., '+=1:30:0')."
    )
    parser_timeshift.set_defaults(func=handle_timeshift)

    # --- 3-pair-jpegs ---
    parser_pair_jpegs = subparsers.add_parser(
        "3-pair-jpegs",
        help="Phase 3: Identifies RAW+JPEG pairs and separates the JPEG file."
    )
    parser_pair_jpegs.set_defaults(func=handle_pair_jpegs)

    # --- 4-by-date ---
    parser_by_date = subparsers.add_parser(
        "4-by-date",
        help="Phase 4: Organizes files into a YYYY-MM-DD directory structure."
    )
    parser_by_date.set_defaults(func=handle_by_date)

    # --- 5-geotag ---
    parser_geotag = subparsers.add_parser(
        "5-geotag",
        help="Phase 5: Applies GPS data from GPX tracks."
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

    # --- 6-to-develop ---
    parser_to_develop = subparsers.add_parser(
        "6-to-develop",
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
