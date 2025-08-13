#!/bin/bash
# Script Name: p04-by-date.sh
# Description: Organizes photo/video files into a 'by-date/YYYY-MM-DD/' directory
#              structure based on EXIF DateTimeOriginal.

# Exit on error, treat unset variables as an error
set -e
set -u

# --- Source Common Configuration ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
# shellcheck source=./photo_workflow_config.sh
source "${SCRIPT_DIR}/photo_workflow_config.sh"
# --- End Source Common Configuration ---


# --- Script-Specific Configuration ---
readonly SCRIPT_MODULE_PREFIX="p04-by-date"
readonly SOURCE_SUBDIR="src"       # Temporary subdirectory for source files
readonly TARGET_BASE_SUBDIR="by-date" # Base directory for date-organized files
# --- End Script-Specific Configuration ---


# Ensure we're in a sane environment
LC_ALL=C
export LC_ALL

# Check for necessary commands
check_commands exiftool find mv mkdir rmdir

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
readonly FILES_NOT_PROCESSED_TXT="${WORKSPACE_DIR}/${SCRIPT_MODULE_PREFIX}-log02-files_not_processed.txt"

# --- Initialize Log/Report Files ---
echo "Photo Organization by Date Log" > "$LOG_PROCESSING_DETAILS_TXT"
echo "Date: $(date)" >> "$LOG_PROCESSING_DETAILS_TXT"
echo "---------------------------------------------------------------------" >> "$LOG_PROCESSING_DETAILS_TXT"
echo "" >> "$LOG_PROCESSING_DETAILS_TXT"

echo "Files Not Processed (e.g., missing DateTimeOriginal or errors)" > "$FILES_NOT_PROCESSED_TXT"
echo "Date: $(date)" >> "$FILES_NOT_PROCESSED_TXT"
echo "---------------------------------------------------------------------" >> "$FILES_NOT_PROCESSED_TXT"
echo "" >> "$FILES_NOT_PROCESSED_TXT"

echo "Photo Organization by Date Summary Report" > "$REPORT_SUMMARY_TXT"
echo "Date: $(date)" >> "$REPORT_SUMMARY_TXT"
echo "---------------------------------------------------------------------" >> "$REPORT_SUMMARY_TXT"

# --- Setup Source and Target Directories in CWD ---
SRC_DIR_PATH="${PWD}/${SOURCE_SUBDIR}"
BY_DATE_DIR_PATH="${PWD}/${TARGET_BASE_SUBDIR}"

mkdir -p "$SRC_DIR_PATH"
mkdir -p "$BY_DATE_DIR_PATH"
echo "Source files will be temporarily moved to: ${SRC_DIR_PATH}" >&2
echo "Organized files will be placed in: ${BY_DATE_DIR_PATH}" >&2


# --- Main Processing Logic ---
files_moved_to_src=0
files_processed_step1=0
files_processed_step2=0
files_left_in_src_count=0

# === STEP 0: Move files to temporary 'src' directory ===
echo ""
echo "--- ${SCRIPT_MODULE_PREFIX}: Step 0: Moving files to '${SOURCE_SUBDIR}' directory ---" >&2
shopt -s extglob

echo "Identifying items to move to '${SRC_DIR_PATH}'..." >> "$LOG_PROCESSING_DETAILS_TXT"
for item in "${PWD}"/*; do
    item_basename=$(basename "$item")
    if [[ "$item_basename" == "$GLOBAL_WORKSPACE_DIR_NAME" ]] || \
       [[ "$item_basename" == "$SOURCE_SUBDIR" ]] || \
       [[ "$item_basename" == "$TARGET_BASE_SUBDIR" ]] || \
       [[ "$item_basename" == "$(basename "$0")" ]] || \
       [[ "$item_basename" == "photo_workflow_config.sh" ]] || \
       [[ "$item_basename" == _* ]]; then 
        echo "  Skipping move: $item_basename (special item or starts with _)" >> "$LOG_PROCESSING_DETAILS_TXT"
        continue
    fi

    if [[ -e "$item" ]]; then 
        echo "  Moving to src: $item_basename" >> "$LOG_PROCESSING_DETAILS_TXT"
        if mv "$item" "$SRC_DIR_PATH/"; then
            files_moved_to_src=$((files_moved_to_src + 1))
        else
            echo "  ERROR: Failed to move '$item' to '$SRC_DIR_PATH'." >> "$LOG_PROCESSING_DETAILS_TXT"
            echo "'$item' (failed to move to src in Step 0)" >> "$FILES_NOT_PROCESSED_TXT"
        fi
    fi
done
shopt -u extglob
echo "Moved $files_moved_to_src item(s) to '${SRC_DIR_PATH}'." >&2
echo "Moved $files_moved_to_src item(s) to '${SRC_DIR_PATH}'." >> "$LOG_PROCESSING_DETAILS_TXT"
echo "--- ${SCRIPT_MODULE_PREFIX}: Step 0 Complete ---" >&2
echo "" >&2


# === STEP 1: Rename files from 'src' into 'by-date' (flat structure) ===
echo "--- ${SCRIPT_MODULE_PREFIX}: Step 1: Renaming files from '${SOURCE_SUBDIR}' into '${TARGET_BASE_SUBDIR}' (flat) ---" >&2
if [[ $files_moved_to_src -gt 0 ]] || [[ -n "$(find "$SRC_DIR_PATH" -mindepth 1 -print -quit)" ]]; then 
    # Construct exiftool arguments carefully to protect exiftool's variables from shell expansion
    target_filename_format_step1="-FileName<${BY_DATE_DIR_PATH}/\${DateTimeOriginal}" # \$ ensures exiftool sees ${DateTimeOriginal}
    date_format_step1="%Y-%m-%d--%H-%M-%S%%-c.%%le"

    echo "Executing: exiftool -overwrite_original -P -r \"${target_filename_format_step1}\" -d \"${date_format_step1}\" \"${SRC_DIR_PATH}\"" >> "$LOG_PROCESSING_DETAILS_TXT"
    
    exiftool_output_step1=$(exiftool -overwrite_original -P -r \
        "${target_filename_format_step1}" \
        -d "${date_format_step1}" \
        "$SRC_DIR_PATH" 2>&1)
    echo "Exiftool Step 1 Output:" >> "$LOG_PROCESSING_DETAILS_TXT"
    echo "$exiftool_output_step1" >> "$LOG_PROCESSING_DETAILS_TXT"
    
    files_processed_step1=$(echo "$exiftool_output_step1" | grep -Eoc "image files (updated|moved)")
    echo "$files_processed_step1 file(s) processed by exiftool in Step 1." >&2
else
    echo "Source directory '${SRC_DIR_PATH}' is empty or only contained items moved in Step 0. Skipping Step 1." >&2
    echo "Source directory '${SRC_DIR_PATH}' is empty or only contained items moved in Step 0. Skipping Step 1." >> "$LOG_PROCESSING_DETAILS_TXT"
fi
echo "--- ${SCRIPT_MODULE_PREFIX}: Step 1 Complete ---" >&2
echo "" >&2


# === STEP 2: Move files from flat 'by-date' into daily subfolders within 'by-date' ===
echo "--- ${SCRIPT_MODULE_PREFIX}: Step 2: Moving files into daily subfolders within '${TARGET_BASE_SUBDIR}' ---" >&2
if [[ -n "$(find "$BY_DATE_DIR_PATH" -mindepth 1 -maxdepth 1 -type f -print -quit)" ]]; then 
    target_directory_format_step2="-Directory<${BY_DATE_DIR_PATH}/\${DateTimeOriginal}" # \$ ensures exiftool sees ${DateTimeOriginal}
    date_format_step2="%Y-%m-%d"

    echo "Executing: exiftool -overwrite_original -P -r \"${target_directory_format_step2}\" -d \"${date_format_step2}\" \"${BY_DATE_DIR_PATH}\"" >> "$LOG_PROCESSING_DETAILS_TXT"
    
    exiftool_output_step2=$(exiftool -overwrite_original -P -r \
        "${target_directory_format_step2}" \
        -d "${date_format_step2}" \
        "$BY_DATE_DIR_PATH" 2>&1) # Source is BY_DATE_DIR_PATH itself
    echo "Exiftool Step 2 Output:" >> "$LOG_PROCESSING_DETAILS_TXT"
    echo "$exiftool_output_step2" >> "$LOG_PROCESSING_DETAILS_TXT"

    files_processed_step2=$(echo "$exiftool_output_step2" | grep -Eoc "image files (updated|moved)")
    echo "$files_processed_step2 file(s) processed by exiftool in Step 2." >&2
else
    echo "Directory '${BY_DATE_DIR_PATH}' has no files at its root to process for Step 2, or Step 1 processed no files into its root. Skipping." >&2
    echo "Directory '${BY_DATE_DIR_PATH}' has no files at its root to process for Step 2, or Step 1 processed no files into its root. Skipping." >> "$LOG_PROCESSING_DETAILS_TXT"
fi
echo "--- ${SCRIPT_MODULE_PREFIX}: Step 2 Complete ---" >&2
echo "" >&2

# === STEP 3: Cleanup and Reporting ===
echo "--- ${SCRIPT_MODULE_PREFIX}: Step 3: Cleanup and Reporting ---" >&2
mapfile -d '' remaining_src_files_array < <(find "$SRC_DIR_PATH" -type f -print0)
files_left_in_src_count=${#remaining_src_files_array[@]}

if [[ $files_left_in_src_count -gt 0 ]]; then
    echo "Warning: $files_left_in_src_count file(s) remain in '${SRC_DIR_PATH}' or its subdirectories. These may have lacked DateTimeOriginal or encountered errors." >&2
    echo "$files_left_in_src_count file(s) remain in '${SRC_DIR_PATH}' or its subdirectories:" >> "$FILES_NOT_PROCESSED_TXT"
    for file_path in "${remaining_src_files_array[@]}"; do
        relative_file_path="${file_path#${PWD}/}" 
        echo "  - ${relative_file_path}" >> "$FILES_NOT_PROCESSED_TXT"
    done
    echo "Unprocessed files listed in '${FILES_NOT_PROCESSED_TXT}'." >> "$LOG_PROCESSING_DETAILS_TXT"
    echo "Note: Unprocessed files remain in '${SRC_DIR_PATH}'. Check '${FILES_NOT_PROCESSED_TXT}'." >&2
fi

echo "Attempting to clean up empty subdirectories within '${SRC_DIR_PATH}'..." >> "$LOG_PROCESSING_DETAILS_TXT"
echo "Cleaning up empty subdirectories within '${SRC_DIR_PATH}'..." >&2
find "$SRC_DIR_PATH" -mindepth 1 -type d -empty -delete 2>/dev/null || true 
echo "Empty subdirectory cleanup attempt complete." >> "$LOG_PROCESSING_DETAILS_TXT"
echo "Empty subdirectory cleanup attempt complete." >&2

if [[ $files_left_in_src_count -eq 0 ]]; then
    if rmdir "$SRC_DIR_PATH" 2>/dev/null; then
        echo "Successfully removed empty source directory: ${SRC_DIR_PATH}" >> "$LOG_PROCESSING_DETAILS_TXT"
        echo "Empty source directory '${SRC_DIR_PATH}' removed." >&2
    else
        if [[ -d "$SRC_DIR_PATH" ]]; then 
             echo "Source directory '${SRC_DIR_PATH}' could not be removed. It might still contain hidden files or non-empty subdirectories not caught by cleanup." >> "$LOG_PROCESSING_DETAILS_TXT"
             echo "Warning: Source directory '${SRC_DIR_PATH}' could not be removed (may not be fully empty). Check for hidden files if no regular files were reported." >&2
        fi
    fi
else
    echo "Source directory '${SRC_DIR_PATH}' not removed as it still contains unprocessed files." >> "$LOG_PROCESSING_DETAILS_TXT"
fi


# --- Generate Summary Report ---
echo "" >> "$REPORT_SUMMARY_TXT"
echo "Processing Summary:" >> "$REPORT_SUMMARY_TXT"
echo "-------------------" >> "$REPORT_SUMMARY_TXT"
echo "Items initially moved to '${SOURCE_SUBDIR}' (Step 0): $files_moved_to_src" >> "$REPORT_SUMMARY_TXT"
echo "Files renamed/moved into '${TARGET_BASE_SUBDIR}' (flat - Step 1): $files_processed_step1" >> "$REPORT_SUMMARY_TXT"
echo "Files moved into daily subfolders within '${TARGET_BASE_SUBDIR}' (Step 2): $files_processed_step2" >> "$REPORT_SUMMARY_TXT"
echo "Files remaining in '${SOURCE_SUBDIR}' (check '${FILES_NOT_PROCESSED_TXT}'): $files_left_in_src_count" >> "$REPORT_SUMMARY_TXT"
echo "" >> "$REPORT_SUMMARY_TXT"
echo "Detailed processing log: ${LOG_PROCESSING_DETAILS_TXT}" >> "$REPORT_SUMMARY_TXT"
echo "List of unprocessed files: ${FILES_NOT_PROCESSED_TXT}" >> "$REPORT_SUMMARY_TXT"
echo "--- ${SCRIPT_MODULE_PREFIX}: Step 3 Complete ---" >&2
echo "" >&2

# --- Final Summary to stdout ---
echo "--- ${SCRIPT_MODULE_PREFIX}: Final Summary ---" >&2
echo "All output files from this module are stored in the workspace directory:" >&2
echo "   ${WORKSPACE_DIR}" >&2
echo "" >&2
echo "Items initially moved to '${SOURCE_SUBDIR}': $files_moved_to_src" >&2
echo "Files renamed/moved into '${TARGET_BASE_SUBDIR}' (flat - Step 1): $files_processed_step1" >&2
echo "Files moved into daily subfolders within '${TARGET_BASE_SUBDIR}' (Step 2): $files_processed_step2" >&2
echo "Files remaining in '${SOURCE_SUBDIR}' (unprocessed): $files_left_in_src_count" >&2
if [[ $files_left_in_src_count -gt 0 ]]; then
    echo "  -> Check list of unprocessed files: ${FILES_NOT_PROCESSED_TXT}" >&2
fi
echo "" >&2
echo "Detailed processing log: ${LOG_PROCESSING_DETAILS_TXT}" >&2
echo "Summary report: ${REPORT_SUMMARY_TXT}" >&2
echo "" >&2
echo "--- ${SCRIPT_MODULE_PREFIX}: Processing Complete ---" >&2
exit 0