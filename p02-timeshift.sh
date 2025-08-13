#!/bin/bash
# Script Name: p02-timeshift.sh
# Description: Shifts EXIF date/time tags in files using exiftool.
#              Moves unprocessable files to '_non_photos',
#              files with no updatable date tags to '_untagged_photos',
#              and exiftool backups to '_originals'.

# Exit on error, treat unset variables as an error
set -e
set -u

# --- Source Common Configuration ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
# shellcheck source=./photo_workflow_config.sh
source "${SCRIPT_DIR}/photo_workflow_config.sh"
# --- End Source Common Configuration ---


# --- Script-Specific Configuration ---
readonly SCRIPT_MODULE_PREFIX="p02-timeshift"
readonly NON_PHOTOS_SUBDIR="_non_photos"
readonly UNTAGGED_PHOTOS_SUBDIR="_untagged_photos"
readonly ORIGINALS_SUBDIR="_originals" # For exiftool backups
# --- End Script-Specific Configuration ---


# Ensure we're in a sane environment
LC_ALL=C
export LC_ALL

# Check for necessary commands
check_commands exiftool find wc mv mkdir

# --- Usage Function ---
usage() {
    echo "Usage: $(basename "$0") \"<SHIFT_OPERATOR><YEARS:MONTHS:DAYS> <HOURS:MINUTES:SECONDS>\""
    echo "Example: $(basename "$0") \"+=0:0:0 1:30:0\""
    echo ""
    echo "Details:"
    echo "  Shifts date/time tags using exiftool's -AllDates option."
    echo "  Backup files (*_original) created by exiftool for modified files are moved to '${ORIGINALS_SUBDIR}'."
    echo "  Files exiftool can't process (errors, unsupported) are moved to '${NON_PHOTOS_SUBDIR}'."
    echo "  Files exiftool processes successfully but finds no date tags to update are moved to '${UNTAGGED_PHOTOS_SUBDIR}'."
    exit 1
}

# --- Argument Validation ---
if [[ $# -ne 1 ]]; then
    echo "Error: Incorrect number of arguments." >&2
    usage
fi

TIME_SHIFT_ARG="$1"

if ! [[ "$TIME_SHIFT_ARG" =~ ^([+-]=)([0-9]{1,}:[0-9]{1,}:[0-9]{1,})[[:space:]]([0-9]{1,}:[0-9]{1,}:[0-9]{1,})$ ]]; then
    echo "Error: Invalid time shift argument format." >&2
    echo "Received: \"$TIME_SHIFT_ARG\"" >&2
    usage
fi

EXIFTOOL_SHIFT_COMMAND="-AllDates${TIME_SHIFT_ARG}"

# --- Workspace Directory Setup ---
WORKSPACE_DIR="${PWD}/${GLOBAL_WORKSPACE_DIR_NAME}"
mkdir -p "$WORKSPACE_DIR"
if [[ ! -d "$WORKSPACE_DIR" ]]; then
    echo "Error: Could not create workspace directory: $WORKSPACE_DIR" >&2; exit 1
fi
echo "All output files from this module will be stored in workspace: $WORKSPACE_DIR" >&2
echo "(Using prefix: ${SCRIPT_MODULE_PREFIX})" >&2

# --- Define File Paths ---
readonly LOG_PROCESSING_DETAILS_TXT="${WORKSPACE_DIR}/${SCRIPT_MODULE_PREFIX}-log01-processing_details.txt"
readonly REPORT_SUMMARY_TXT="${WORKSPACE_DIR}/${SCRIPT_MODULE_PREFIX}-report01-summary.txt"
readonly MOVED_FILES_LOG_TXT="${WORKSPACE_DIR}/${SCRIPT_MODULE_PREFIX}-log02-moved_files.txt"

# --- Initialize Log/Report Files ---
echo "Time Shift Operation Log - Command: exiftool ${EXIFTOOL_SHIFT_COMMAND}" > "$LOG_PROCESSING_DETAILS_TXT"
echo "Date: $(date)" >> "$LOG_PROCESSING_DETAILS_TXT"
echo "---------------------------------------------------------------------" >> "$LOG_PROCESSING_DETAILS_TXT"
echo "" >> "$LOG_PROCESSING_DETAILS_TXT"

echo "Moved Files Log" > "$MOVED_FILES_LOG_TXT"
echo "Date: $(date)" >> "$MOVED_FILES_LOG_TXT"
echo "Log of files moved to '${NON_PHOTOS_SUBDIR}', '${UNTAGGED_PHOTOS_SUBDIR}', or '${ORIGINALS_SUBDIR}'." >> "$MOVED_FILES_LOG_TXT"
echo "---------------------------------------------------------------------" >> "$MOVED_FILES_LOG_TXT"
echo "" >> "$MOVED_FILES_LOG_TXT"

echo "Time Shift Summary Report - Command: exiftool ${EXIFTOOL_SHIFT_COMMAND}" > "$REPORT_SUMMARY_TXT"
echo "Date: $(date)" >> "$REPORT_SUMMARY_TXT"
echo "---------------------------------------------------------------------" >> "$REPORT_SUMMARY_TXT"

# --- Create target subdirectories in the CWD ---
TARGET_DIR_NON_PHOTOS="${PWD}/${NON_PHOTOS_SUBDIR}"
TARGET_DIR_UNTAGGED_PHOTOS="${PWD}/${UNTAGGED_PHOTOS_SUBDIR}"
TARGET_DIR_ORIGINALS="${PWD}/${ORIGINALS_SUBDIR}"
mkdir -p "$TARGET_DIR_NON_PHOTOS"
mkdir -p "$TARGET_DIR_UNTAGGED_PHOTOS"
mkdir -p "$TARGET_DIR_ORIGINALS"
echo "Unprocessable files will be moved to: ${TARGET_DIR_NON_PHOTOS}" >&2
echo "Files with no updatable date tags will be moved to: ${TARGET_DIR_UNTAGGED_PHOTOS}" >&2
echo "Exiftool original backup files will be moved to: ${TARGET_DIR_ORIGINALS}" >&2


# --- Function to move file to a target directory with collision avoidance ---
# Arguments: $1 = source_filepath, $2 = target_base_directory, $3 = reason_for_move
#            $4 = (optional) new_base_filename_no_ext (if renaming before moving, e.g. removing _original suffix)
move_file_robustly() {
    local source_filepath="$1"
    local target_base_dir="$2"
    local reason="$3"
    local new_base_filename_no_ext_opt="${4:-}" # Optional new base name without extension
    local base_filename
    local extension
    local base_filename_no_ext # This will be the base for collision checking
    local destination_filename
    local destination_path
    local counter=0

    base_filename=$(basename "$source_filepath") # Original base name from source

    if [[ -n "$new_base_filename_no_ext_opt" ]]; then
        # Use the provided new base name and try to determine extension from original file
        extension="${base_filename##*.}" # Get extension from original name
        if [[ "$base_filename" == "$extension" ]] || [[ "$extension" == "original" ]]; then # if original has no ext or ext is "_original"
            # If original file was 'file_original' or 'file.txt_original', then ext is 'original'
            # We need to find the "true" extension if new_base_filename_no_ext_opt is e.g. 'file' or 'file.txt'
             temp_base_for_ext_check="$new_base_filename_no_ext_opt"
             extension="${temp_base_for_ext_check##*.}"
             if [[ "$temp_base_for_ext_check" == "$extension" ]]; then # new base has no ext
                extension=""
             fi
        fi
        base_filename_no_ext="$new_base_filename_no_ext_opt"
        # Strip extension from new_base_filename_no_ext_opt if it was accidentally included
        if [[ -n "$extension" ]]; then
             base_filename_no_ext="${new_base_filename_no_ext_opt%.${extension}}"
        fi

    else # No new base name provided, use the source's base name
        extension="${base_filename##*.}"
        if [[ "$base_filename" == "$extension" ]]; then # No extension
            base_filename_no_ext="$base_filename"
            extension=""
        else
            base_filename_no_ext="${base_filename%.*}"
        fi
    fi

    # Construct initial destination filename based on (potentially new) base_filename_no_ext and extension
    if [[ -n "$extension" ]]; then
        destination_filename="${base_filename_no_ext}.${extension}"
    else
        destination_filename="${base_filename_no_ext}"
    fi
    destination_path="${target_base_dir}/${destination_filename}"

    # Handle collisions
    while [[ -e "$destination_path" ]]; do
        counter=$((counter + 1))
        if [[ -n "$extension" ]]; then
            destination_filename="${base_filename_no_ext}-$(printf "%02d" "$counter").${extension}"
        else
            destination_filename="${base_filename_no_ext}-$(printf "%02d" "$counter")"
        fi
        destination_path="${target_base_dir}/${destination_filename}"
    done

    if mv -n "$source_filepath" "$destination_path"; then
        echo "MOVED: '$source_filepath' to '$destination_path' (Reason: $reason)" >> "$MOVED_FILES_LOG_TXT"
        return 0 # Success
    else
        echo "ERROR moving '$source_filepath' to '$destination_path'. Please check permissions or disk space." >> "$MOVED_FILES_LOG_TXT"
        echo "  Status: CRITICAL ERROR - Failed to move '$source_filepath' to '$destination_path'." >> "$LOG_PROCESSING_DETAILS_TXT"
        return 1 # Failure
    fi
}


# --- Main Processing Logic ---
# === STAGE 1: APPLYING TIME SHIFT ===
echo ""
echo "--- ${SCRIPT_MODULE_PREFIX}: Stage 1: Applying Time Shift ---" >&2
echo "Using exiftool command part: ${EXIFTOOL_SHIFT_COMMAND}" >&2
echo "Processing files recursively in the current directory: $(pwd)" >&2

processed_count=0
modified_count=0
error_count=0
moved_to_non_photos_count=0
moved_to_untagged_photos_count=0

# Exclude all our special subdirectories from the find command
mapfile -d $'\0' file_list < <(find . -type d \( -name "${NON_PHOTOS_SUBDIR}" -o -name "${UNTAGGED_PHOTOS_SUBDIR}" -o -name "${ORIGINALS_SUBDIR}" \) -prune -o -type f -print0)
total_files=${#file_list[@]}
echo "Found $total_files files to scan (excluding special subdirectories)." >&2
current_file_num=0

for filepath_rel in "${file_list[@]}"; do
    filepath="$filepath_rel"

    ((++current_file_num))
    if [[ $total_files -gt 0 ]]; then
        percentage=$((current_file_num * 100 / total_files))
        printf "\rStage 1 Processing: %d%% (%d/%d) - Current: %s                                     " "$percentage" "$current_file_num" "$total_files" "$filepath" >&2
    else
        printf "\rStage 1 Processing: %s                                     " "$filepath" >&2
    fi

    exiftool_output=$(exiftool -m "${EXIFTOOL_SHIFT_COMMAND}" "$filepath" 2>&1)
    
    echo calling exiftool -m "${EXIFTOOL_SHIFT_COMMAND}" "$filepath" 
    echo $filepath
    echo $exiftool_output
    
    
    
    
    exiftool_exit_status=$?
    processed_count=$((processed_count + 1))

    echo "File: $filepath" >> "$LOG_PROCESSING_DETAILS_TXT"
    action_successful=0

    if [[ $exiftool_exit_status -eq 0 ]]; then
        if [[ "$exiftool_output" == *"1 image files updated"* ]]; then
            echo "  Status: SUCCESS - Tags updated." >> "$LOG_PROCESSING_DETAILS_TXT"; modified_count=$((modified_count + 1)); action_successful=1
        elif [[ "$exiftool_output" == *"0 image files updated"* ]]; then
            echo "  Status: NO DATE TAGS TO UPDATE (moving to ${UNTAGGED_PHOTOS_SUBDIR})" >> "$LOG_PROCESSING_DETAILS_TXT"
            if move_file_robustly "$filepath" "$TARGET_DIR_UNTAGGED_PHOTOS" "No updatable date tags"; then
                moved_to_untagged_photos_count=$((moved_to_untagged_photos_count + 1)); action_successful=1
            else error_count=$((error_count + 1)); fi
        else
            echo "  Status: UNEXPECTED EXIFTOOL OUTPUT (Exit 0, moving to ${NON_PHOTOS_SUBDIR})" >> "$LOG_PROCESSING_DETAILS_TXT"
            if move_file_robustly "$filepath" "$TARGET_DIR_NON_PHOTOS" "Exiftool exit 0 with unexpected output"; then
                moved_to_non_photos_count=$((moved_to_non_photos_count + 1)); action_successful=1
            else error_count=$((error_count + 1)); fi
        fi
        echo "  Output: $exiftool_output" >> "$LOG_PROCESSING_DETAILS_TXT" # Log output for all exit 0 cases
    else # exiftool_exit_status is non-zero
        reason_for_move="Exiftool error (Code: $exiftool_exit_status)"
        target_dir_for_error="$TARGET_DIR_NON_PHOTOS"
        log_message_prefix="EXIFTOOL ERROR"

        if [[ "$exiftool_output" == *"File not found"* ]]; then
             echo "  Status: ERROR - File not found by exiftool. Not moved." >> "$LOG_PROCESSING_DETAILS_TXT"; error_count=$((error_count + 1)); action_successful=1
        elif [[ "$exiftool_output" == *"files failed condition"* ]] || [[ "$exiftool_output" == *"Error:"* ]] || [[ "$exiftool_output" == *"Nothing to do."* ]]; then
            reason_for_move="Unsupported by exiftool or unreadable"
            log_message_prefix="UNSUPPORTED/UNREADABLE"
        fi
        # Common handling for moving files on error (unless it was "File not found")
        if [[ "$exiftool_output" != *"File not found"* ]]; then
            echo "  Status: $log_message_prefix (moving to ${target_dir_for_error}) - ${reason_for_move}." >> "$LOG_PROCESSING_DETAILS_TXT"
            if move_file_robustly "$filepath" "$target_dir_for_error" "$reason_for_move"; then
                moved_to_non_photos_count=$((moved_to_non_photos_count + 1)); action_successful=1
            else error_count=$((error_count + 1)); fi
        fi
        echo "  Output: $exiftool_output" >> "$LOG_PROCESSING_DETAILS_TXT" # Log output for all non-zero exit cases
    fi

    if [[ $action_successful -eq 0 ]]; then
        echo "  Status: CRITICAL - File processing not handled. File NOT moved. Please review logic." >> "$LOG_PROCESSING_DETAILS_TXT"
        echo "  Output: $exiftool_output (Exit Code: $exiftool_exit_status)" >> "$LOG_PROCESSING_DETAILS_TXT"
        error_count=$((error_count + 1))
    fi
    echo "" >> "$LOG_PROCESSING_DETAILS_TXT"
done
printf "\nStage 1 Processing complete.\n" >&2
echo "--- ${SCRIPT_MODULE_PREFIX}: Stage 1 Complete ---" >&2
echo "" >&2


# === STAGE 2: MOVING EXIFTOOL BACKUP (*_original) FILES ===
echo "--- ${SCRIPT_MODULE_PREFIX}: Stage 2: Moving Exiftool Original Backups ---" >&2
moved_originals_count=0
# Find files ending with _original, ensuring we don't try to process files already in our special dirs
mapfile -d $'\0' original_files_list < <(find . -type d \( -name "${NON_PHOTOS_SUBDIR}" -o -name "${UNTAGGED_PHOTOS_SUBDIR}" -o -name "${ORIGINALS_SUBDIR}" \) -prune -o -type f -name '*_original' -print0)
total_original_files=${#original_files_list[@]}
current_original_file_num=0

if [[ $total_original_files -gt 0 ]]; then
    echo "Found $total_original_files exiftool backup (*_original) files to move." >&2
    for original_filepath_rel in "${original_files_list[@]}"; do
        original_filepath="$original_filepath_rel"
        ((++current_original_file_num))
        printf "\rStage 2 Moving Originals: %d%% (%d/%d) - Current: %s                     " \
            "$((current_original_file_num * 100 / total_original_files))" \
            "$current_original_file_num" "$total_original_files" "$original_filepath" >&2

        # Remove the "_original" suffix for the new base name
        new_base_name="${original_filepath%_original}"
        # We need just the filename part of new_base_name if it included path
        new_base_filename_no_ext_for_mv=$(basename "$new_base_name")


        if move_file_robustly "$original_filepath" "$TARGET_DIR_ORIGINALS" "Exiftool backup" "$new_base_filename_no_ext_for_mv"; then
            moved_originals_count=$((moved_originals_count + 1))
        else
            # Error moving, already logged by move_file_robustly, count it here
            error_count=$((error_count + 1))
            # Log specific failure to main log too
            echo "File: $original_filepath" >> "$LOG_PROCESSING_DETAILS_TXT"
            echo "  Status: ERROR - Failed to move this _original file to ${TARGET_DIR_ORIGINALS}." >> "$LOG_PROCESSING_DETAILS_TXT"
            echo "" >> "$LOG_PROCESSING_DETAILS_TXT"
        fi
    done
    printf "\nStage 2 Moving Originals complete.\n" >&2
else
    echo "No exiftool backup (*_original) files found to move." >&2
fi
echo "--- ${SCRIPT_MODULE_PREFIX}: Stage 2 Complete ---" >&2
echo "" >&2


# === STAGE 3: SUMMARY REPORT GENERATION (was previously report stage) ===
# This stage doesn't exist anymore as a separate data processing step,
# summary is built from counters. The report file definition is kept for consistency.
# We'll just write the final summary here.

# --- Generate Summary Report ---
echo "--- ${SCRIPT_MODULE_PREFIX}: Stage 3: Generating Summary Report ---" >&2
echo "" >> "$REPORT_SUMMARY_TXT" # Start with a blank line if appending to existing date header
echo "Processing Summary:" >> "$REPORT_SUMMARY_TXT"
echo "-------------------" >> "$REPORT_SUMMARY_TXT"
echo "Total files scanned (initial find): $total_files" >> "$REPORT_SUMMARY_TXT"
echo "Total files processed by exiftool (Stage 1): $processed_count" >> "$REPORT_SUMMARY_TXT"
echo "Files successfully time-shifted (Stage 1): $modified_count" >> "$REPORT_SUMMARY_TXT"
echo "Exiftool backup files moved to '${ORIGINALS_SUBDIR}' (Stage 2): $moved_originals_count" >> "$REPORT_SUMMARY_TXT"
echo "Files moved to '${UNTAGGED_PHOTOS_SUBDIR}' (processed, no date tags to update - Stage 1): $moved_to_untagged_photos_count" >> "$REPORT_SUMMARY_TXT"
echo "Files moved to '${NON_PHOTOS_SUBDIR}' (unsupported, errors, etc. - Stage 1): $moved_to_non_photos_count" >> "$REPORT_SUMMARY_TXT"
echo "Files with errors (not moved or move failed): $error_count" >> "$REPORT_SUMMARY_TXT"
echo "" >> "$REPORT_SUMMARY_TXT"
echo "Detailed processing log (Stages 1 & 2): ${LOG_PROCESSING_DETAILS_TXT}" >> "$REPORT_SUMMARY_TXT"
echo "Log of all moved files (Stages 1 & 2): ${MOVED_FILES_LOG_TXT}" >> "$REPORT_SUMMARY_TXT"
echo "--- ${SCRIPT_MODULE_PREFIX}: Stage 3 Complete ---" >&2
echo "" >&2


# --- Final Summary to stdout ---
echo "--- ${SCRIPT_MODULE_PREFIX}: Final Summary ---" >&2
echo "All output files from this module are stored in the workspace directory:" >&2
echo "   ${WORKSPACE_DIR}" >&2
echo "" >&2
echo "Total files scanned (initial find): $total_files" >&2
echo "Total files processed by exiftool (Stage 1): $processed_count" >&2
echo "Files successfully time-shifted (Stage 1): $modified_count" >&2
echo "Exiftool backup files moved to '${ORIGINALS_SUBDIR}' (Stage 2): $moved_originals_count" >&2
echo "Files moved to '${UNTAGGED_PHOTOS_SUBDIR}' (processed, no date tags to update - Stage 1): $moved_to_untagged_photos_count" >&2
echo "Files moved to '${NON_PHOTOS_SUBDIR}' (unsupported, errors, etc. - Stage 1): $moved_to_non_photos_count" >&2
echo "Files with errors (not moved or move failed): $error_count" >&2
echo "" >&2
echo "Detailed processing log: ${LOG_PROCESSING_DETAILS_TXT}" >&2
echo "Log of all moved files: ${MOVED_FILES_LOG_TXT}" >&2
echo "Summary report: ${REPORT_SUMMARY_TXT}" >&2
echo "" >&2
echo "--- ${SCRIPT_MODULE_PREFIX}: Processing Complete ---" >&2
exit 0
