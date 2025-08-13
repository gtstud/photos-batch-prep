#!/bin/bash
# Script Name: p06-to-develop.sh
# Description: Identifies folders needing further processing based on missing files.
#              - Lists folders containing SRW files that lack corresponding TIF/TIFF files in any subfolder.
#              - Lists folders containing TIF files that lack corresponding *__std.jpg files in their parent folder.
#              Prints the final lists of identified folders at the very end of execution.

# Exit on error, treat unset variables as an error
set -e
set -u

# --- Source Common Configuration ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
# shellcheck source=./photo_workflow_config.sh
source "${SCRIPT_DIR}/photo_workflow_config.sh"
# --- End Source Common Configuration ---


# --- Script-Specific Configuration ---
readonly SCRIPT_MODULE_PREFIX="p06-to-develop"
# --- End Script-Specific Configuration ---


# Ensure we're in a sane environment
LC_ALL=C
export LC_ALL

# Check for necessary commands
check_commands find basename dirname realpath sort uniq wc echo grep mkdir tail

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
readonly REPORT_FOLDERS_MISSING_TIFS_TXT="${WORKSPACE_DIR}/${SCRIPT_MODULE_PREFIX}-report02-folders_missing_tifs.txt"
readonly REPORT_FOLDERS_MISSING_STD_JPGS_TXT="${WORKSPACE_DIR}/${SCRIPT_MODULE_PREFIX}-report03-folders_missing_std_jpgs.txt"

# Intermediate files for collecting raw folder paths before sorting/uniquifying
readonly TMP_FOLDERS_MISSING_TIFS_RAW="${WORKSPACE_DIR}/${SCRIPT_MODULE_PREFIX}-tmp01-folders_missing_tifs_raw.list"
readonly TMP_FOLDERS_MISSING_STD_JPGS_RAW="${WORKSPACE_DIR}/${SCRIPT_MODULE_PREFIX}-tmp02-folders_missing_std_jpgs_raw.list"

# --- Initialize Log/Report Files ---
echo "Folder Analysis Log for Missing Files" > "$LOG_PROCESSING_DETAILS_TXT"
echo "Date: $(date)" >> "$LOG_PROCESSING_DETAILS_TXT"
echo "Scanning from: ${PWD}" >> "$LOG_PROCESSING_DETAILS_TXT"
echo "---------------------------------------------------------------------" >> "$LOG_PROCESSING_DETAILS_TXT"
echo "" >> "$LOG_PROCESSING_DETAILS_TXT"

# Initialize main report file
echo "Folder Analysis Summary Report" > "$REPORT_SUMMARY_TXT"
echo "Date: $(date)" >> "$REPORT_SUMMARY_TXT"
echo "Scanning from: ${PWD}" >> "$REPORT_SUMMARY_TXT"
echo "---------------------------------------------------------------------" >> "$REPORT_SUMMARY_TXT"

# Initialize specific report files and temporary files
echo "# Folders containing SRW files with no corresponding TIF/TIFF in any subfolder" > "$REPORT_FOLDERS_MISSING_TIFS_TXT"
echo "# Date: $(date)" >> "$REPORT_FOLDERS_MISSING_TIFS_TXT"
> "$TMP_FOLDERS_MISSING_TIFS_RAW"

echo "# Folders containing TIF/TIFF files with no corresponding *__std.jpg in the parent folder" > "$REPORT_FOLDERS_MISSING_STD_JPGS_TXT"
echo "# Date: $(date)" >> "$REPORT_FOLDERS_MISSING_STD_JPGS_TXT"
> "$TMP_FOLDERS_MISSING_STD_JPGS_RAW"


# --- Helper Function ---
# Get base name without extension (case-insensitive for specific extensions)
get_base_name() {
    local filename="$1"
    local base
    base=$(basename "$filename")
    # Handle common extensions case-insensitively
    shopt -s nocasematch
    if [[ "$base" == *.srw ]]; then
        base="${base%.srw}"
    elif [[ "$base" == *.tif ]]; then
        base="${base%.tif}"
    elif [[ "$base" == *.tiff ]]; then
        base="${base%.tiff}"
    elif [[ "$base" == *.jpg ]]; then
        base="${base%.jpg}"
    elif [[ "$base" == *.jpeg ]]; then
        base="${base%.jpeg}"
    else
        # Fallback for unknown extensions
        base="${base%.*}"
    fi
    shopt -u nocasematch
    echo "$base"
}


# --- Stage 1: Find folders with SRW but no TIF/TIFF in subfolders ---
echo ""
echo "--- ${SCRIPT_MODULE_PREFIX}: Stage 1: Identifying folders with SRW files missing TIF/TIFF counterparts in subfolders ---" >&2
folders_found_missing_tifs=0
srw_files_processed=0

# Find all SRW files, excluding special _* directories at the top level
mapfile -d $'\0' srw_file_list < <(find . -type d -name '_*' -prune -o -type f -iname "*.srw" -print0)
total_srw_files=${#srw_file_list[@]}
echo "Found $total_srw_files potential SRW files to check." >&2
current_srw_num=0

for srw_filepath_rel in "${srw_file_list[@]}"; do
    ((++current_srw_num)) # Prefix increment
    srw_files_processed=$((srw_files_processed + 1))

    # Use realpath -m to handle potential symlinks and get a canonical absolute path
    srw_filepath_abs="$(realpath -m "$srw_filepath_rel")"
    srw_dir_abs="$(dirname "$srw_filepath_abs")"
    srw_base_name_no_ext=$(get_base_name "$srw_filepath_abs") # Use helper for base name

    printf "\rStage 1 Processing: %d%% (%d/%d) - Checking SRW: %s                     " \
        "$((current_srw_num * 100 / total_srw_files))" \
        "$current_srw_num" "$total_srw_files" "$srw_filepath_rel" >&2

    # Search for the corresponding TIF/TIFF within subfolders of the SRW's directory ONLY (-mindepth 1)
    tif_search_output=$(find "$srw_dir_abs" -mindepth 1 -type f \( -iname "${srw_base_name_no_ext}.tif" -o -iname "${srw_base_name_no_ext}.tiff" \) -print -quit)
    tif_found=0 # Assume not found initially

    if [[ -n "$tif_search_output" ]]; then
        tif_found=1
    fi

    if [[ $tif_found -eq 0 ]]; then
        echo "Processing SRW: '$srw_filepath_abs'" >> "$LOG_PROCESSING_DETAILS_TXT"
        echo "  -> FAIL: Corresponding TIF/TIFF ('${srw_base_name_no_ext}.tif[f]') NOT found in any subfolder of '$srw_dir_abs'." >> "$LOG_PROCESSING_DETAILS_TXT"
        echo "$srw_dir_abs" >> "$TMP_FOLDERS_MISSING_TIFS_RAW"
    fi
done
printf "\nStage 1 SRW file scanning complete.\n" >&2

# Process the raw list: sort, unique, and write to final report
if [[ -s "$TMP_FOLDERS_MISSING_TIFS_RAW" ]]; then
    sort -u "$TMP_FOLDERS_MISSING_TIFS_RAW" >> "$REPORT_FOLDERS_MISSING_TIFS_TXT"
    folders_found_missing_tifs=$(($(wc -l < "$REPORT_FOLDERS_MISSING_TIFS_TXT") - 2))
    if [[ $folders_found_missing_tifs -lt 0 ]]; then folders_found_missing_tifs=0; fi

    echo "Identified $folders_found_missing_tifs unique folders potentially needing TIF/TIFF generation." >&2
    echo "Report written to: ${REPORT_FOLDERS_MISSING_TIFS_TXT}" >&2
    # *** REMOVED printing here ***
else
    echo "No folders found containing SRW files without corresponding TIFs/TIFFs in subfolders." >&2
    echo "# No folders found matching criteria." >> "$REPORT_FOLDERS_MISSING_TIFS_TXT"
    folders_found_missing_tifs=0
fi

echo "--- ${SCRIPT_MODULE_PREFIX}: Stage 1 Complete ---" >&2
echo "" >&2


# --- Stage 2: Find folders with TIF but no parent *__std.jpg ---
echo "--- ${SCRIPT_MODULE_PREFIX}: Stage 2: Identifying folders with TIF/TIFF files missing parent *__std.jpg counterparts ---" >&2
folders_found_missing_std_jpgs=0
tif_files_processed=0

# Find all TIF/TIFF files, excluding special _* directories at the top level
mapfile -d $'\0' tif_file_list < <(find . -type d -name '_*' -prune -o -type f \( -iname "*.tif" -o -iname "*.tiff" \) -print0)
total_tif_files=${#tif_file_list[@]}
echo "Found $total_tif_files potential TIF/TIFF files to check." >&2
current_tif_num=0

for tif_filepath_rel in "${tif_file_list[@]}"; do
    ((++current_tif_num)) # Prefix increment
    tif_files_processed=$((tif_files_processed + 1))

    tif_filepath_abs="$(realpath -m "$tif_filepath_rel")"
    tif_dir_abs="$(dirname "$tif_filepath_abs")"
    parent_dir_abs="$(dirname "$tif_dir_abs")"
    tif_base_name_no_ext=$(get_base_name "$tif_filepath_abs")

    printf "\rStage 2 Processing: %d%% (%d/%d) - Checking TIF: %s                     " \
        "$((current_tif_num * 100 / total_tif_files))" \
        "$current_tif_num" "$total_tif_files" "$tif_filepath_rel" >&2

    expected_std_jpg_path_lc="${parent_dir_abs}/${tif_base_name_no_ext}__std.jpg"
    expected_std_jpg_path_uc="${parent_dir_abs}/${tif_base_name_no_ext}__std.JPG"

    echo "Processing TIF: '$tif_filepath_abs'" >> "$LOG_PROCESSING_DETAILS_TXT"
    echo "  -> Checking for Standard JPG: '${parent_dir_abs}/${tif_base_name_no_ext}__std.jpg' (case-insensitive)" >> "$LOG_PROCESSING_DETAILS_TXT"

    std_jpg_found=0
    if [[ -f "$expected_std_jpg_path_lc" || -f "$expected_std_jpg_path_uc" ]]; then
        std_jpg_found=1
    fi

    if [[ $std_jpg_found -eq 0 ]]; then
        echo "  -> FAIL: Standard JPG NOT found." >> "$LOG_PROCESSING_DETAILS_TXT"
        echo "$tif_dir_abs" >> "$TMP_FOLDERS_MISSING_STD_JPGS_RAW"
    else
        echo "  -> OK: Standard JPG found." >> "$LOG_PROCESSING_DETAILS_TXT"
    fi
done
printf "\nStage 2 TIF file scanning complete.\n" >&2

# Process the raw list: sort, unique, and write to final report
if [[ -s "$TMP_FOLDERS_MISSING_STD_JPGS_RAW" ]]; then
    sort -u "$TMP_FOLDERS_MISSING_STD_JPGS_RAW" >> "$REPORT_FOLDERS_MISSING_STD_JPGS_TXT"
    folders_found_missing_std_jpgs=$(($(wc -l < "$REPORT_FOLDERS_MISSING_STD_JPGS_TXT") - 2))
     if [[ $folders_found_missing_std_jpgs -lt 0 ]]; then folders_found_missing_std_jpgs=0; fi

    echo "Identified $folders_found_missing_std_jpgs unique folders potentially needing Standard JPG generation." >&2
    echo "Report written to: ${REPORT_FOLDERS_MISSING_STD_JPGS_TXT}" >&2
    # *** REMOVED printing here ***
else
    echo "No folders found containing TIF/TIFF files without corresponding *__std.jpg files in the parent folder." >&2
    echo "# No folders found matching criteria." >> "$REPORT_FOLDERS_MISSING_STD_JPGS_TXT"
    folders_found_missing_std_jpgs=0
fi

echo "--- ${SCRIPT_MODULE_PREFIX}: Stage 2 Complete ---" >&2
echo "" >&2


# --- Generate Summary Report ---
echo "--- ${SCRIPT_MODULE_PREFIX}: Generating Summary Report ---" >&2
{
    echo ""
    echo "Processing Summary:"
    echo "-------------------"
    echo "Stage 1 (SRW without TIF/TIFF in subfolder):"
    echo "  SRW files scanned: $srw_files_processed"
    echo "  Unique folders identified needing TIFs/TIFFs: $folders_found_missing_tifs"
    echo "  Report file: ${REPORT_FOLDERS_MISSING_TIFS_TXT}"
    echo ""
    echo "Stage 2 (TIF/TIFF without parent *__std.jpg):"
    echo "  TIF/TIFF files scanned: $tif_files_processed"
    echo "  Unique folders identified needing Standard JPGs: $folders_found_missing_std_jpgs"
    echo "  Report file: ${REPORT_FOLDERS_MISSING_STD_JPGS_TXT}"
    echo ""
    echo "Detailed processing log: ${LOG_PROCESSING_DETAILS_TXT}"
} >> "$REPORT_SUMMARY_TXT"
echo "Summary report generated: ${REPORT_SUMMARY_TXT}" >&2
echo "--- ${SCRIPT_MODULE_PREFIX}: Summary Report Generation Complete ---" >&2
echo "" >&2


# --- Final Summary to stdout ---
echo "--- ${SCRIPT_MODULE_PREFIX}: Final Summary ---" >&2
echo "All output files from this module are stored in the workspace directory:" >&2
echo "   ${WORKSPACE_DIR}" >&2
echo "" >&2
echo "Analysis Results Summary:" >&2
echo " -> Folders with SRW files potentially needing TIF/TIFF generation (missing in subfolders): $folders_found_missing_tifs" >&2
echo "    (List follows if any found. Also in report: ${REPORT_FOLDERS_MISSING_TIFS_TXT})" >&2
echo " -> Folders with TIF/TIFF files potentially needing Standard JPG generation (missing in parent folder): $folders_found_missing_std_jpgs" >&2
echo "    (List follows if any found. Also in report: ${REPORT_FOLDERS_MISSING_STD_JPGS_TXT})" >&2
echo "" >&2
echo "Detailed processing log: ${LOG_PROCESSING_DETAILS_TXT}" >&2
echo "Summary report: ${REPORT_SUMMARY_TXT}" >&2
echo "" >&2

# *** ADDED: Print final lists at the end ***
if [[ $folders_found_missing_tifs -gt 0 ]]; then
    echo "" >&2
    echo "---------------------------------------------------------------------" >&2
    echo "Folders needing TIF/TIFF generation (SRW found, TIF/TIFF missing in subfolder):" >&2
    echo "---------------------------------------------------------------------" >&2
    # Use tail to skip the first 2 header lines in the report file
    tail -n +3 "$REPORT_FOLDERS_MISSING_TIFS_TXT" | while IFS= read -r line; do
       echo "  $line" >&2 # Print with indentation
    done
fi

if [[ $folders_found_missing_std_jpgs -gt 0 ]]; then
    echo "" >&2
    echo "---------------------------------------------------------------------" >&2
    echo "Folders needing Standard JPG generation (TIF/TIFF found, *__std.jpg missing in parent):" >&2
    echo "---------------------------------------------------------------------" >&2
    # Use tail to skip the first 2 header lines in the report file
    tail -n +3 "$REPORT_FOLDERS_MISSING_STD_JPGS_TXT" | while IFS= read -r line; do
       echo "  $line" >&2 # Print with indentation
    done
fi
# *** END ADDED SECTION ***

echo "" >&2 # Add a final blank line for separation
echo "--- ${SCRIPT_MODULE_PREFIX}: Processing Complete ---" >&2
exit 0
