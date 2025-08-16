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

def _scan_and_hash_files(exclude_dirs: set[Path], checksum_algo: str, logger) -> tuple[list, defaultdict]:
    """
    Scans for files recursively, avoiding specified directories, and calculates their checksums.

    Args:
        exclude_dirs: A set of resolved absolute paths to exclude from the scan.
        checksum_algo: The hashing algorithm to use.
        logger: The logger instance.

    Returns:
        A tuple containing:
        - file_data: A list of dictionaries, each with info about a file.
        - files_by_name: A defaultdict grouping file_info dicts by filename.
    """
    logger.info("Scanning all files recursively in the current directory...")
    file_data = []
    files_by_name = defaultdict(list)
    files_to_scan = []

    for root, _, files in os.walk("."):
        root_path = Path(root).resolve()
        if any(str(root_path).startswith(str(ex_dir)) for ex_dir in exclude_dirs):
            continue
        for name in files:
            files_to_scan.append(Path(root) / name)

    for filepath in tqdm(files_to_scan, desc="Hashing files"):
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
    return file_data, files_by_name


def _move_duplicates(file_data: list, trash_dir: Path, args, logger):
    """
    Identifies duplicate files based on size and checksum, and moves them to the trash directory.

    Args:
        file_data: A list of file information dictionaries from _scan_and_hash_files.
        trash_dir: The directory where duplicates will be moved.
        args: The command-line arguments (for dry_run).
        logger: The logger instance.
    """
    files_by_identity = defaultdict(list)
    for info in file_data:
        key = (info["size"], info["checksum"])
        files_by_identity[key].append(info)

    duplicates_found = 0
    for _, items in sorted(files_by_identity.items()):
        if len(items) > 1:
            items.sort(key=lambda x: x["path"])  # Keep the one with the shortest path
            for dup in items[1:]:
                duplicates_found += 1
                logger.info(f"Found duplicate: '{dup['path']}' (original: '{items[0]['path']}')")
                if args.dry_run:
                    logger.info(f"DRY RUN: Would move '{dup['path']}' to '{trash_dir}'")
                else:
                    # _move_file_robustly handles its own errors, logging, and name collisions.
                    _move_file_robustly(dup['path'], trash_dir, args.dry_run)

    if duplicates_found > 0:
        logger.info(f"Found and moved {duplicates_found} duplicate files to trash directory: {trash_dir}")
    else:
        logger.info("No duplicate files found.")


def _generate_conflict_report(files_by_name: defaultdict, report_path: Path, args, logger):
    """
    Generates a report for files that have the same name but different checksums.

    Args:
        files_by_name: A defaultdict grouping file info by filename.
        report_path: The path to write the report to.
        args: The command-line arguments (for dry_run).
        logger: The logger instance.
    """
    conflicts_found = 0
    report_content = ["# Report on files with the same name but different checksums.\n\n"]

    for name, items in sorted(files_by_name.items()):
        unique_checksums = {item["checksum"] for item in items}
        if len(unique_checksums) > 1:
            conflicts_found += 1
            report_content.append(f"Filename: '{name}' has {len(items)} instances with {len(unique_checksums)} different versions:\n")
            for item in sorted(items, key=lambda x: x["checksum"]):
                report_content.append(f"  - Checksum: {item['checksum']}, Size: {item['size']}, Path: '{item['path']}'\n")
            report_content.append("\n")

    if conflicts_found > 0:
        logger.info(f"Found {conflicts_found} files with conflicting versions. Report written to: {report_path}")
        if not args.dry_run:
            with open(report_path, "w", encoding="utf-8") as f:
                f.write("".join(report_content))
    else:
        logger.info("No conflicting file versions found.")
        # Don't leave an empty report file
        if report_path.exists():
            report_path.unlink()


def handle_dedup(args, config):
    """
    Phase 1: Finds duplicate files and files with naming conflicts.

    This function orchestrates the deduplication process by:
    1. Scanning and hashing all files in the current directory.
    2. Identifying files with identical content (size + checksum) and moving duplicates to a trash folder.
    3. Generating a report for files that share a name but have different content.
    """
    logger.info("Running '1-dedup' command...")

    # --- Setup Paths ---
    workspace_dir = Path.cwd() / config["workspace_dir"]
    trash_dir = Path.cwd() / config.get("duplicates_trash_dir", "_duplicates_trash")
    conflict_report_path = workspace_dir / "p01-dedup-report-conflicting-versions.txt"

    if not args.dry_run:
        workspace_dir.mkdir(exist_ok=True)
        trash_dir.mkdir(exist_ok=True)

    logger.info(f"Workspace directory: {workspace_dir}")
    logger.info(f"Trash directory for duplicates: {trash_dir}")

    # --- Main Logic ---
    checksum_algo = config["dedup"]["checksum_algorithm"]
    logger.info(f"Using '{checksum_algo}' checksum algorithm.")

    exclude_dirs = {workspace_dir.resolve(), trash_dir.resolve()}
    file_data, files_by_name = _scan_and_hash_files(exclude_dirs, checksum_algo, logger)

    if file_data:
        _move_duplicates(file_data, trash_dir, args, logger)
        _generate_conflict_report(files_by_name, conflict_report_path, args, logger)

    logger.info("'1-dedup' command complete.")


def _move_file_preserving_structure(source_path: Path, dest_root: Path, base_dir: Path, dry_run: bool):
    """
    Moves a file to a new root directory, preserving its relative path from a base directory.
    e.g., move 'base/sub/file.txt' to 'dest/sub/file.txt'
    """
    if not source_path.exists():
        return None

    try:
        relative_path = source_path.relative_to(base_dir)
    except ValueError:
        logger.warning(f"Could not determine relative path for {source_path} from {base_dir}. Skipping.")
        return None

    destination_path = dest_root / relative_path

    if dry_run:
        logger.info(f"DRY RUN: Would move '{source_path}' to '{destination_path}'")
        return destination_path

    try:
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(source_path, destination_path)
        return destination_path
    except OSError as e:
        logger.error(f"Error moving file {source_path} to {destination_path}: {e}")
        return None

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

def _calculate_timeshift_offset(args, logger) -> str | None:
    """
    Calculates the exiftool offset string from argparse arguments.

    Returns the offset string or None if the input is invalid.
    """
    if args.offset:
        if any([args.days, args.hours, args.minutes, args.seconds]):
            logger.error("Error: Cannot use --offset simultaneously with specific time unit flags (e.g., --hours).")
            return None
        # Validate the provided offset format
        offset_pattern = re.compile(r"^[+-]?=\d{1,}:\d{1,}:\d{1,}( \d{1,}:\d{1,}:\d{1,})?$")
        if not offset_pattern.match(args.offset):
            logger.error(f"Invalid offset format: '{args.offset}'. Expected format like '+=Y:M:D H:M:S'.")
            return None
        return args.offset

    # If --offset is not used, build it from other flags
    if not any([args.days, args.hours, args.minutes, args.seconds]):
        logger.error("Error: No time shift specified. Use --offset or provide at least one time unit flag (e.g., --hours).")
        return None

    # Using timedelta to handle positive/negative shifts easily
    delta = timedelta(days=args.days, hours=args.hours, minutes=args.minutes, seconds=args.seconds)
    total_seconds = delta.total_seconds()

    if total_seconds == 0:
        return "0"  # A zero shift is a valid no-op

    sign = "+=" if total_seconds >= 0 else "-="
    s = abs(int(total_seconds))

    days = s // 86400
    s %= 86400
    hours = s // 3600
    s %= 3600
    minutes = s // 60
    seconds = s % 60

    # exiftool format is Y:M:D H:M:S. We don't support Year/Month, so they are 0.
    return f"{sign}0:0:{days} {hours}:{minutes}:{seconds}"


def handle_timeshift(args, config):
    """
    Phase 2: Shifts EXIF date/time tags in files using exiftool.

    This command corrects the 'AllDates' tag (which includes DateTimeOriginal,
    CreateDate, and ModifyDate) for all files in the current directory. It is
    useful for correcting the timestamp when a camera's clock was set incorrectly.
    Files are sorted into output directories based on whether the operation
    succeeded, failed, or was not applicable.
    """
    logger.info("Running '2-timeshift' command...")

    offset_str = _calculate_timeshift_offset(args, logger)
    if offset_str is None:
        return 1  # Error already logged

    if offset_str == "0":
        logger.info("Time shift is zero. No changes will be made. Command complete.")
        return 0

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
    exiftool_cmd = f"-AllDates{offset_str}"

    try:
        with exiftool.ExifToolHelper() as et:
            for filepath in tqdm(files_to_process, desc="Shifting timestamps"):
                if args.dry_run:
                    logger.info(f"DRY RUN: Would run exiftool on '{filepath}' with offset '{offset_str}'")
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
    Phase 3: Identifies RAW+JPEG pairs and moves the "extra" JPEG to a separate directory.

    For photographers who shoot in RAW+JPEG mode, this command finds pairs where the
    RAW file and JPEG share the same base name. It verifies they are a true pair by
    comparing EXIF metadata (Camera Model and Timestamp) and moves the JPEG file
    to the '_extra_jpgs' directory if they match.
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


def _collect_files_for_by_date(config: dict, logger) -> tuple[list[Path], Path]:
    """
    Collects all files to be processed by the 'by-date' command, excluding special directories.

    Args:
        config: The application configuration dictionary.
        logger: The logger instance.

    Returns:
        A tuple containing:
        - A list of file paths to process.
        - The path to the 'by-date' destination directory.
    """
    by_date_dir = Path.cwd() / "by-date"
    workspace_dir = Path.cwd() / config["workspace_dir"]

    exclude_dirs = {by_date_dir.resolve(), workspace_dir.resolve()}
    for d in Path.cwd().glob("_*"):
        if d.is_dir():
            exclude_dirs.add(d.resolve())

    files_to_process = []
    for p in Path.cwd().rglob("*"):
        if not p.is_file():
            continue

        # Exclude files inside special directories
        if any(str(p.resolve()).startswith(str(ex_dir)) for ex_dir in exclude_dirs):
            continue

        # Exclude script-related files in the root directory
        if p.parent.resolve() == Path.cwd().resolve() and p.name in ("photoflow.py", "pyproject.toml", "README.md", "specification.md", ".gitignore"):
            continue

        files_to_process.append(p)

    logger.info(f"Found {len(files_to_process)} files to organize.")
    return files_to_process, by_date_dir


def handle_by_date(args, config):
    """
    Phase 4: Organizes files into a 'by-date/YYYY-MM-DD/' directory structure based on EXIF date.

    This function reads the 'DateTimeOriginal' tag from each file and moves it into a
    date-stamped folder, renaming the file to match the timestamp (e.g., '2023-10-27--15-30-00.jpg').
    """
    logger.info("Running '4-by-date' command...")

    files_to_process, by_date_dir = _collect_files_for_by_date(config, logger)

    if not args.dry_run:
        by_date_dir.mkdir(exist_ok=True)
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


def _get_files_without_gps(files_to_check: list[Path]) -> tuple[list[Path], list[Path]]:
    """
    Scans a list of files and returns two lists: those with GPS data and those without.
    """
    files_with_gps = []
    files_without_gps = []

    if not files_to_check:
        return [], []

    logger.info(f"Checking {len(files_to_check)} files for existing GPS data...")

    def chunked_list(lst, n):
        """Yield successive n-sized chunks from lst."""
        for i in range(0, len(lst), n):
            yield lst[i:i + n]

    try:
        with exiftool.ExifToolHelper() as et:
            with tqdm(total=len(files_to_check), desc="Checking for existing GPS") as pbar:
                for chunk in chunked_list(files_to_check, 100):
                    try:
                        metadata_list = et.get_tags([str(p) for p in chunk], tags=["GPSLatitude"])
                        for i, metadata in enumerate(metadata_list):
                            if "EXIF:GPSLatitude" in metadata or "Composite:GPSLatitude" in metadata:
                                files_with_gps.append(chunk[i])
                            else:
                                files_without_gps.append(chunk[i])
                    except Exception as e:
                        logger.warning(f"Could not process a chunk of files while checking for GPS: {e}")
                    finally:
                        pbar.update(len(chunk))
    except Exception as e:
        logger.error(f"Failed to read EXIF data with pyexiftool: {e}")
        # If we fail here, assume no files can be processed.
        return files_to_check, []

    return files_with_gps, files_without_gps


def handle_geotag(args, config):
    """
    Phase 5: Applies GPS data from GPX tracks using a two-pass approach.
    Pass 1: Standard interpolation.
    Pass 2: Extrapolation for remaining files (last known location).
    """
    logger.info("Running '5-geotag' command...")

    # --- 1. Setup and Pre-flight Checks ---
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
        logger.error(f"Target directory '{target_dir.name}' not found. Please run '4-by-date' first.")
        return 1

    last_gps_dir = Path.cwd() / "last-gps"
    no_gps_dir = Path.cwd() / "no-gps"
    if not args.dry_run:
        last_gps_dir.mkdir(exist_ok=True)
        no_gps_dir.mkdir(exist_ok=True)

    all_files = [p for p in target_dir.rglob("*") if p.is_file()]
    logger.info(f"Found {len(all_files)} total files in '{target_dir.name}'.")
    if not all_files:
        logger.info("'5-geotag' command complete.")
        return

    # --- 2. Initial Scan for GPS Data ---
    already_tagged, files_to_geotag_pass1 = _get_files_without_gps(all_files)
    logger.info(f"Found {len(already_tagged)} files that are already geotagged and will be skipped.")

    if not files_to_geotag_pass1:
        logger.info("No new files to geotag.")
        logger.info("'5-geotag' command complete.")
        return

    # --- 3. Pass 1: Standard Geotagging (Interpolation) ---
    logger.info(f"--- Pass 1: Attempting to geotag {len(files_to_geotag_pass1)} files using standard interpolation. ---")

    geotime_arg = f"-geotime<${{DateTimeOriginal}}{args.timezone}"
    gpx_pattern = str(gpx_dir.resolve() / "*.gpx")
    pass1_updated_count = 0

    if not args.dry_run:
        try:
            with exiftool.ExifToolHelper() as et:
                params = ["-overwrite_original", "-P", geotime_arg, "-geotag", gpx_pattern]
                files_str = [str(p) for p in files_to_geotag_pass1]
                output = et.execute(*params, *files_str)

                updated_summary = re.search(r"(\d+) image files updated", output)
                if updated_summary:
                    pass1_updated_count = int(updated_summary.group(1))
                logger.debug(f"Exiftool Pass 1 output:\n{output}")
                if et.last_stderr:
                    logger.warning(f"Exiftool Pass 1 reported errors:\n{et.last_stderr}")
        except Exception as e:
            logger.error(f"An error occurred during geotagging Pass 1: {e}")

    # --- 4. Re-scan and Move for Pass 2 ---
    logger.info("Checking for files that were not geotagged in Pass 1.")
    _, files_for_pass2 = _get_files_without_gps(files_to_geotag_pass1)

    logger.info(f"Moving {len(files_for_pass2)} files that failed Pass 1 to '{last_gps_dir.name}'.")
    moved_to_last_gps_count = 0
    files_in_last_gps = []
    for f in files_for_pass2:
        moved_path = _move_file_preserving_structure(f, last_gps_dir, target_dir.parent, args.dry_run)
        if moved_path:
            moved_to_last_gps_count += 1
            files_in_last_gps.append(moved_path)

    if not files_in_last_gps:
        logger.info("No files needed to be moved for Pass 2.")

    # --- 5. Pass 2: Extrapolation Geotagging ---
    pass2_updated_count = 0
    if files_in_last_gps:
        logger.info(f"--- Pass 2: Attempting to geotag {len(files_in_last_gps)} files using extrapolation. ---")
        if not args.dry_run:
            try:
                with exiftool.ExifToolHelper() as et:
                    params = [
                        "-api", "GeoMaxIntSecs=0",
                        "-api", "GeoMaxExtSecs=86400",
                        "-overwrite_original", "-P", geotime_arg, "-geotag", gpx_pattern
                    ]
                    files_str = [str(p) for p in files_in_last_gps]
                    output = et.execute(*params, *files_str)

                    updated_summary = re.search(r"(\d+) image files updated", output)
                    if updated_summary:
                        pass2_updated_count = int(updated_summary.group(1))
                    logger.debug(f"Exiftool Pass 2 output:\n{output}")
                    if et.last_stderr:
                        logger.warning(f"Exiftool Pass 2 reported errors:\n{et.last_stderr}")
            except Exception as e:
                logger.error(f"An error occurred during geotagging Pass 2: {e}")

    # --- 6. Final Scan and Move Failures ---
    logger.info("Checking for files that were not geotagged in Pass 2.")
    _, final_failures = _get_files_without_gps(files_in_last_gps)

    logger.info(f"Moving {len(final_failures)} files that failed Pass 2 to '{no_gps_dir.name}'.")
    moved_to_no_gps_count = 0
    for f in final_failures:
        if _move_file_preserving_structure(f, no_gps_dir, last_gps_dir.parent, args.dry_run):
            moved_to_no_gps_count += 1

    # --- 7. Summary ---
    logger.info("\n--- Geotag Summary ---")
    logger.info(f"Files skipped (already had GPS data): {len(already_tagged)}")
    logger.info(f"Files geotagged in Pass 1 (interpolation): {pass1_updated_count}")
    logger.info(f"Files moved to '{last_gps_dir.name}' for Pass 2: {moved_to_last_gps_count}")
    logger.info(f"Files geotagged in Pass 2 (extrapolation): {pass2_updated_count}")
    logger.info(f"Files that could not be geotagged (moved to '{no_gps_dir.name}'): {moved_to_no_gps_count}")
    logger.info("'5-geotag' command complete.")


def handle_to_develop(args, config):
    """
    Phase 6: Reports on files needing development work in a RAW -> TIF -> JPG workflow.

    This command is for users with an advanced development workflow. It scans the
    directory and generates a report on two conditions:
    1. RAW files that are missing a corresponding TIF file.
    2. TIF files that are missing a final, standard-output JPEG (named '__std.jpg').
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


def handle_move_no_gps(args, config):
    """
    Miscellaneous: Moves all photo files recursively that have no GPS information to a 'non-gps' subfolder.
    """
    logger.info("Running 'move-no-gps' command...")

    non_gps_dir = Path.cwd() / "non-gps"
    if not args.dry_run:
        non_gps_dir.mkdir(exist_ok=True)

    photo_ext = tuple(f".{ext}".lower() for ext in config["file_formats"]["raw"] + config["file_formats"]["image"])

    # Collect all files first
    all_files = [p for p in Path.cwd().rglob("*") if p.is_file()]

    # Filter for photo files, excluding files already in the destination directory
    files_to_check = []
    for p in all_files:
        if str(p.resolve()).startswith(str(non_gps_dir.resolve())):
            continue
        if p.suffix.lower() in photo_ext:
            files_to_check.append(p)

    logger.info(f"Found {len(files_to_check)} photo files to check for GPS data.")
    if not files_to_check:
        logger.info("'move-no-gps' command complete.")
        return

    moved_count = 0

    def chunked_list(lst, n):
        """Yield successive n-sized chunks from lst."""
        for i in range(0, len(lst), n):
            yield lst[i:i + n]

    try:
        with exiftool.ExifToolHelper() as et:
            with tqdm(total=len(files_to_check), desc="Checking for GPS data") as pbar:
                for chunk in chunked_list(files_to_check, 100):
                    try:
                        metadata_list = et.get_tags([str(p) for p in chunk], tags=["GPSLatitude"])
                        for metadata in metadata_list:
                            source_file = Path(metadata["SourceFile"])
                            if "EXIF:GPSLatitude" not in metadata and "Composite:GPSLatitude" not in metadata:
                                if _move_file_preserving_structure(source_file, non_gps_dir, Path.cwd(), args.dry_run):
                                    moved_count += 1
                    except Exception as e:
                        logger.warning(f"Could not process a chunk of files: {e}")
                    finally:
                        pbar.update(len(chunk))
    except Exception as e:
        logger.error(f"An error occurred during 'move-no-gps' processing: {e}")
        return

    logger.info("\n--- Move No-GPS Summary ---")
    logger.info(f"Moved {moved_count} files without GPS data to '{non_gps_dir.name}'.")
    logger.info("'move-no-gps' command complete.")


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
            "The commands are broken down into two groups:\n\n"
            "--- Workflow Phases ---\n"
            "A recommended, numbered sequence of operations for a full workflow:\n"
            "  1. dedup         (Find and separate duplicate files of any type)\n"
            "  2. timeshift     (Correct EXIF timestamps if a camera clock was wrong)\n"
            "  3. pair-jpegs    (Separate RAW+JPEG pairs)\n"
            "  4. by-date       (Organize files into a date-based folder structure)\n"
            "  5. geotag        (Add GPS data from GPX tracks using a two-pass system)\n"
            "  6. to-develop    (Report on files needing development, e.g. RAW->TIF)\n\n"
            "--- Miscellaneous Commands ---\n"
            "  move-no-gps    (Find and separate any photos that have no GPS data)"
        ),
        epilog="Use 'photoflow <command> --help' for more information on a specific command.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose debug output.")
    parser.add_argument("--dry-run", action="store_true", help="Simulate actions without making any changes to files.")

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # --- 1-dedup ---
    parser_dedup = phase_parsers.add_parser(
        "dedup",
        help="Phase 1: Finds duplicate files and files with naming conflicts."
    )
    parser_dedup.set_defaults(func=handle_dedup)

    # --- 2-timeshift ---
    parser_timeshift = phase_parsers.add_parser(
        "timeshift",
        help="Phase 2: Shifts EXIF timestamps for a batch of files.",
        description="Corrects camera timestamps. You can specify the shift using --offset for advanced use, "
                    "or with user-friendly flags like --hours and --minutes for simpler adjustments.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    timeshift_group = parser_timeshift.add_argument_group(
        "Time Shift Options", "Specify the time shift using one of the following methods"
    )
    timeshift_group.add_argument(
        "--offset",
        help="The time shift specification string (e.g., '+=1:30:0' or '-=0:0:1 2:0:0'). For advanced use."
    )
    timeshift_group.add_argument("--days", type=int, default=0, help="Number of days to shift (can be negative).")
    timeshift_group.add_argument("--hours", type=int, default=0, help="Number of hours to shift (can be negative).")
    timeshift_group.add_argument("--minutes", type=int, default=0, help="Number of minutes to shift (can be negative).")
    timeshift_group.add_argument("--seconds", type=int, default=0, help="Number of seconds to shift (can be negative).")
    parser_timeshift.set_defaults(func=handle_timeshift)

    # --- 3-pair-jpegs ---
    parser_pair_jpegs = phase_parsers.add_parser(
        "pair-jpegs",
        help="Phase 3: Identifies RAW+JPEG pairs and separates the JPEG file."
    )
    parser_pair_jpegs.set_defaults(func=handle_pair_jpegs)

    # --- 4-by-date ---
    parser_by_date = phase_parsers.add_parser(
        "by-date",
        help="Phase 4: Organizes files into a YYYY-MM-DD directory structure."
    )
    parser_by_date.set_defaults(func=handle_by_date)

    # --- 5-geotag ---
    parser_geotag = phase_parsers.add_parser(
        "geotag",
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
    parser_to_develop = phase_parsers.add_parser(
        "to-develop",
        help="Phase 6: Identifies folders that require further processing steps."
    )
    parser_to_develop.set_defaults(func=handle_to_develop)

    # --- move-no-gps ---
    parser_move_no_gps = subparsers.add_parser(
        "move-no-gps",
        help="Moves all photo files with no GPS data to a 'non-gps' folder."
    )
    parser_move_no_gps.set_defaults(func=handle_move_no_gps)


    # --- Parse Arguments and Execute ---
    args = parser.parse_args()

    # If no command is given, print help and exit gracefully.
    if not hasattr(args, "command") or not args.command:
        parser.print_help()
        sys.exit(0)

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
