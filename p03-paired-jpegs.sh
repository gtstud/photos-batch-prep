#!/bin/bash
# Script Name: p03-paired-jpegs.sh
# Description: Identifies JPG/SRW pairs. SRW EXIF is read only if a JPG by name is found.
#              Uses SamsungModelID and DateTimeOriginal (with +/-1s tolerance for DateTimeOriginal).
#              Moves paired JPGs to an '_extra_jpgs' subdirectory.

# Exit on error, treat unset variables as an error
set -e
set -u

# --- Source Common Configuration ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
# shellcheck source=./photo_workflow_config.sh
source "${SCRIPT_DIR}/photo_workflow_config.sh"
# --- End Source Common Configuration ---


# --- Script-Specific Configuration ---
readonly SCRIPT_MODULE_PREFIX="p03-paired-jpegs"
readonly EXTRA_JPGS_SUBDIR="_extra_jpgs"
# Tags to compare for pairing
readonly TAG_MODEL="SamsungModelID"
readonly TAG_DATETIME_ORIGINAL="DateTimeOriginal"
# Tag to log but not strictly compare for pairing
readonly TAG_LENS_SN_LOG_ONLY="InternalLensSerialNumber"
readonly DATETIME_TOLERANCE_SECONDS=1 # JPG can be +/- this many seconds relative to SRW
# --- End Script-Specific Configuration ---


# Ensure we're in a sane environment
LC_ALL=C
export LC_ALL

# Check for necessary commands
check_commands exiftool find wc mv mkdir basename dirname date 

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

# --- Initialize Log/Report Files ---
echo "Paired JPGs Movement and Verification Log" > "$LOG_PROCESSING_DETAILS_TXT"
echo "Date: $(date)" >> "$LOG_PROCESSING_DETAILS_TXT"
echo "JPG files moved to '${EXTRA_JPGS_SUBDIR}' after filename and EXIF tag verification with SRW files." >> "$LOG_PROCESSING_DETAILS_TXT"
echo "Mandatory tags for pairing: ${TAG_MODEL}, ${TAG_DATETIME_ORIGINAL} (DateTimeOriginal tolerance: +/-${DATETIME_TOLERANCE_SECONDS}s)" >> "$LOG_PROCESSING_DETAILS_TXT"
echo "Logged (not for pairing): ${TAG_LENS_SN_LOG_ONLY}" >> "$LOG_PROCESSING_DETAILS_TXT"
echo "---------------------------------------------------------------------" >> "$LOG_PROCESSING_DETAILS_TXT"
echo "" >> "$LOG_PROCESSING_DETAILS_TXT"

echo "Paired JPGs Summary Report" > "$REPORT_SUMMARY_TXT"
echo "Date: $(date)" >> "$REPORT_SUMMARY_TXT"
echo "---------------------------------------------------------------------" >> "$REPORT_SUMMARY_TXT"

# --- Create target subdirectory in the CWD ---
TARGET_DIR_EXTRA_JPGS="${PWD}/${EXTRA_JPGS_SUBDIR}"
mkdir -p "$TARGET_DIR_EXTRA_JPGS"
echo "Paired JPG files will be moved to: ${TARGET_DIR_EXTRA_JPGS}" >&2


# --- Function to move file to a target directory with collision avoidance ---
move_file_robustly() {
    local source_filepath="$1"
    local target_base_dir="$2"
    local reason="$3"
    local base_filename extension base_filename_no_ext
    local destination_filename destination_path
    local counter=0

    base_filename=$(basename "$source_filepath")
    extension="${base_filename##*.}"
    if [[ "$base_filename" == "$extension" ]]; then 
        base_filename_no_ext="$base_filename"; extension=""
    else
        base_filename_no_ext="${base_filename%.*}"
    fi

    destination_filename="$base_filename"
    destination_path="${target_base_dir}/${destination_filename}"

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
        return 0
    else
        echo "ERROR moving '$source_filepath' to '$destination_path'. Check permissions/disk space." >> "$LOG_PROCESSING_DETAILS_TXT"
        return 1
    fi
}

# --- Function to extract specific tags using exiftool ---
get_exif_tags() {
    local file="$1"; shift
    local tags_to_extract=(); local tag_name
    for tag_name in "$@"; do tags_to_extract+=("-${tag_name}"); done

    if ! command -v exiftool &> /dev/null; then
        echo "CRITICAL_ERROR: exiftool command not found INSIDE get_exif_tags for file '$file'" >&2
        for ((i=0; i<$#; i++)); do echo ""; done; return 1 
    fi

    local exiftool_results exiftool_exit_code exiftool_raw_output processed_output
    exiftool_results=$( ( exiftool -s3 -q "${tags_to_extract[@]}" "$file" ; echo "EXIFTOOL_EC:$?" ) 2>&1 )
    exiftool_exit_code=$(echo "$exiftool_results" | tail -n 1 | cut -d':' -f2)
    exiftool_raw_output=$(echo "$exiftool_results" | sed '$d') 
    processed_output=$(echo "$exiftool_raw_output" | awk '{if ($0 == "-") print ""; else print $0}')
    echo "$processed_output"
    
    if [[ "$exiftool_exit_code" -eq 0 || "$exiftool_exit_code" -eq 1 ]]; then return 0
    else return "$exiftool_exit_code"; fi
}

# --- Function to convert YYYY:MM:DD HH:MM:SS to epoch seconds ---
datetime_to_epoch() {
    local datetime_str="$1"; local epoch_secs=""
    local formatted_datetime_str

    if [[ -n "$datetime_str" ]]; then
        formatted_datetime_str="${datetime_str/:/-}" 
        formatted_datetime_str="${formatted_datetime_str/:/-}" 
        epoch_secs=$(date -d "$formatted_datetime_str" +%s 2>/dev/null) || epoch_secs=""
    fi
    echo "$epoch_secs"
}


# --- Main Processing Logic ---
echo ""
echo "--- ${SCRIPT_MODULE_PREFIX}: Stage 1: Identifying Paired JPG/SRW Files ---" >&2
echo "Processing files recursively in the current directory: $(pwd)" >&2
echo "Detailed log will be in: ${LOG_PROCESSING_DETAILS_TXT}" >&2

moved_jpg_count=0
srw_files_found_by_find=0
srw_processed_for_tags_count=0
potential_pairs_by_name_count=0
error_moving_count=0
srw_missing_tags_count=0
jpg_missing_tags_count=0
tag_mismatch_count=0
datetime_conversion_errors=0

mapfile -d $'\0' srw_file_list < <(find . -type d -name '_*' -prune -o -type f -iname "*.SRW" -print0)
total_srw_files_from_find=${#srw_file_list[@]}
echo "Found $total_srw_files_from_find potential SRW files to scan (excluding _* directories)." >&2
current_srw_num_in_list=0

for srw_filepath_rel in "${srw_file_list[@]}"; do
    srw_filepath="$srw_filepath_rel"
    ((++current_srw_num_in_list))
    srw_files_found_by_find=$((srw_files_found_by_find + 1))

    printf "\rScanning SRW files: %d%% (%d/%d) - Current SRW: %s                                     " \
        "$((current_srw_num_in_list * 100 / total_srw_files_from_find))" \
        "$current_srw_num_in_list" "$total_srw_files_from_find" "$srw_filepath" >&2

    # 1. Find potential JPG counterparts by filename FIRST
    dir_name=$(dirname "$srw_filepath")
    base_name_srw=$(basename "$srw_filepath")
    base_name_no_ext_srw="${base_name_srw%.[sS][rR][wW]}"

    jpg_found_by_name=""
    for jpg_ext in "JPG" "jpg" "JPEG" "jpeg"; do
        potential_jpg_path="${dir_name}/${base_name_no_ext_srw}.${jpg_ext}"
        if [[ -f "$potential_jpg_path" ]]; then
            jpg_found_by_name="$potential_jpg_path"
            break
        fi
    done

    if [[ -z "$jpg_found_by_name" ]]; then
        echo "---" >> "$LOG_PROCESSING_DETAILS_TXT" 
        echo "Processing SRW: '$srw_filepath'" >> "$LOG_PROCESSING_DETAILS_TXT"
        echo "  JPG Match: No JPG counterpart found by filename." >> "$LOG_PROCESSING_DETAILS_TXT"
        continue 
    fi
    
    echo "---" >> "$LOG_PROCESSING_DETAILS_TXT" 
    echo "Processing SRW: '$srw_filepath'" >> "$LOG_PROCESSING_DETAILS_TXT"
    echo "  JPG Match: Potential JPG found by name: '$jpg_found_by_name'" >> "$LOG_PROCESSING_DETAILS_TXT"
    potential_pairs_by_name_count=$((potential_pairs_by_name_count + 1))
    srw_processed_for_tags_count=$((srw_processed_for_tags_count+1))


    # 2. Extract tags from SRW
    tags_output_buffer_srw=$(get_exif_tags "$srw_filepath" "$TAG_MODEL" "$TAG_DATETIME_ORIGINAL" "$TAG_LENS_SN_LOG_ONLY")
    get_tags_exit_status_srw=$? 

    if [[ $get_tags_exit_status_srw -ne 0 ]]; then
        echo "  SRW Info: SKIPPED PAIR - Failed to process SRW tags with exiftool (Error code: $get_tags_exit_status_srw)." >> "$LOG_PROCESSING_DETAILS_TXT"
        srw_missing_tags_count=$((srw_missing_tags_count + 1)) 
        continue
    fi
    
    mapfile -t srw_tags < <(printf "%s\n" "$tags_output_buffer_srw")
    srw_model="${srw_tags[0]:-}"
    srw_datetime_str="${srw_tags[1]:-}" 
    srw_lens_sn="${srw_tags[2]:-}"

    if [[ -z "$srw_model" || -z "$srw_datetime_str" ]]; then
        echo "  SRW Info: SKIPPED PAIR - Missing essential tags from SRW (Model: '${srw_model}', DateTimeOriginal: '${srw_datetime_str}'). LensSN (logged): '${srw_lens_sn}'." >> "$LOG_PROCESSING_DETAILS_TXT"
        srw_missing_tags_count=$((srw_missing_tags_count + 1))
        continue
    fi
    
    srw_epoch=$(datetime_to_epoch "$srw_datetime_str")
    if [[ -z "$srw_epoch" ]]; then
        echo "  SRW Info: SKIPPED PAIR - Could not convert SRW DateTimeOriginal ('$srw_datetime_str') to epoch." >> "$LOG_PROCESSING_DETAILS_TXT"
        srw_missing_tags_count=$((srw_missing_tags_count + 1)) 
        datetime_conversion_errors=$((datetime_conversion_errors + 1))
        continue
    fi
    echo "  SRW Info: Model='${srw_model}', DateTime='${srw_datetime_str}' (Epoch: ${srw_epoch}), LensSN (logged)='${srw_lens_sn}'" >> "$LOG_PROCESSING_DETAILS_TXT"


    # 3. Extract tags from potential JPG counterpart
    tags_output_buffer_jpg=$(get_exif_tags "$jpg_found_by_name" "$TAG_MODEL" "$TAG_DATETIME_ORIGINAL" "$TAG_LENS_SN_LOG_ONLY")
    get_tags_exit_status_jpg=$?
    
    if [[ $get_tags_exit_status_jpg -ne 0 ]]; then
        echo "  JPG Info: SKIPPED PAIR - Failed to process JPG tags with exiftool (Error code: $get_tags_exit_status_jpg)." >> "$LOG_PROCESSING_DETAILS_TXT"
        jpg_missing_tags_count=$((jpg_missing_tags_count + 1)) 
        continue
    fi

    mapfile -t jpg_tags < <(printf "%s\n" "$tags_output_buffer_jpg")
    jpg_model="${jpg_tags[0]:-}"
    jpg_datetime_str="${jpg_tags[1]:-}"
    jpg_lens_sn="${jpg_tags[2]:-}"

    if [[ -z "$jpg_model" || -z "$jpg_datetime_str" ]]; then
        echo "  JPG Info: SKIPPED PAIR - JPG missing essential tags (Model: '${jpg_model}', DateTimeOriginal: '${jpg_datetime_str}'). LensSN (logged): '${jpg_lens_sn}'." >> "$LOG_PROCESSING_DETAILS_TXT"
        jpg_missing_tags_count=$((jpg_missing_tags_count + 1))
        continue
    fi

    jpg_epoch=$(datetime_to_epoch "$jpg_datetime_str")
    if [[ -z "$jpg_epoch" ]]; then
        echo "  JPG Info: SKIPPED PAIR - Could not convert JPG DateTimeOriginal ('$jpg_datetime_str') to epoch." >> "$LOG_PROCESSING_DETAILS_TXT"
        jpg_missing_tags_count=$((jpg_missing_tags_count + 1))
        datetime_conversion_errors=$((datetime_conversion_errors + 1))
        continue
    fi
    echo "  JPG Info: Model='${jpg_model}', DateTime='${jpg_datetime_str}' (Epoch: ${jpg_epoch}), LensSN (logged)='${jpg_lens_sn}'" >> "$LOG_PROCESSING_DETAILS_TXT"


    # 4. Compare MANDATORY tags (Model and DateTimeOriginal with tolerance)
    tags_match=1
    if [[ "$srw_model" != "$jpg_model" ]]; then
        echo "  Verification: FAILED - Model mismatch ('${srw_model}' vs '${jpg_model}')" >> "$LOG_PROCESSING_DETAILS_TXT"; tags_match=0
    fi
    
    time_diff=$((jpg_epoch - srw_epoch))
    # Check if the time difference is within [-TOLERANCE, TOLERANCE]
    if ! ( (( time_diff >= -DATETIME_TOLERANCE_SECONDS )) && (( time_diff <= DATETIME_TOLERANCE_SECONDS )) ); then
        echo "  Verification: FAILED - DateTimeOriginal mismatch (SRW Epoch: ${srw_epoch}, JPG Epoch: ${jpg_epoch}, Diff: ${time_diff}s, Tolerance: +/-${DATETIME_TOLERANCE_SECONDS}s)" >> "$LOG_PROCESSING_DETAILS_TXT"; tags_match=0
    fi

    if [[ "$srw_lens_sn" != "$jpg_lens_sn" ]]; then
        echo "  Lens SN Info (not for pairing): Mismatch or one empty ('${srw_lens_sn}' vs '${jpg_lens_sn}')" >> "$LOG_PROCESSING_DETAILS_TXT"
    else
        if [[ -n "$srw_lens_sn" ]]; then
             echo "  Lens SN Info (not for pairing): Match ('${srw_lens_sn}')" >> "$LOG_PROCESSING_DETAILS_TXT"
        fi
    fi

    if [[ $tags_match -eq 1 ]]; then
        echo "  Verification: SUCCESS - Mandatory tags match (within tolerance for DateTimeOriginal)." >> "$LOG_PROCESSING_DETAILS_TXT"
        if move_file_robustly "$jpg_found_by_name" "$TARGET_DIR_EXTRA_JPGS" "Paired with ${srw_filepath} (EXIF verified)"; then
            moved_jpg_count=$((moved_jpg_count + 1))
            echo "  Action: MOVED '$jpg_found_by_name' to '${TARGET_DIR_EXTRA_JPGS}'" >> "$LOG_PROCESSING_DETAILS_TXT"
        else
            error_moving_count=$((error_moving_count + 1))
            echo "  Action: FAILED TO MOVE '$jpg_found_by_name'" >> "$LOG_PROCESSING_DETAILS_TXT"
        fi
    else
        tag_mismatch_count=$((tag_mismatch_count + 1))
        echo "  Action: JPG not moved due to mandatory tag mismatch." >> "$LOG_PROCESSING_DETAILS_TXT"
    fi
done

printf "\nSRW file scanning complete.\n" >&2


# --- Generate Summary Report ---
echo "" >> "$REPORT_SUMMARY_TXT"
echo "Processing Summary:" >> "$REPORT_SUMMARY_TXT"
echo "-------------------" >> "$REPORT_SUMMARY_TXT"
echo "Total SRW files found by find: $total_srw_files_from_find" >> "$REPORT_SUMMARY_TXT"
echo "SRW files with a JPG counterpart by name: $potential_pairs_by_name_count" >> "$REPORT_SUMMARY_TXT"
echo "SRW files processed for EXIF tags (because a JPG was found by name): $srw_processed_for_tags_count" >> "$REPORT_SUMMARY_TXT"
echo "SRW files (from pairs) missing essential tags or DateTime conversion error: $srw_missing_tags_count" >> "$REPORT_SUMMARY_TXT"
echo "JPG files (from pairs) missing essential tags or DateTime conversion error: $jpg_missing_tags_count" >> "$REPORT_SUMMARY_TXT"
echo "DateTime conversion errors (total for SRW+JPG in pairs): $datetime_conversion_errors" >> "$REPORT_SUMMARY_TXT"
echo "Pairs with mandatory EXIF tag mismatches (Model or DateTime outside tolerance): $tag_mismatch_count" >> "$REPORT_SUMMARY_TXT"
echo "JPG files successfully verified and moved to '${EXTRA_JPGS_SUBDIR}': $moved_jpg_count" >> "$REPORT_SUMMARY_TXT"
echo "Errors encountered while moving JPG files: $error_moving_count" >> "$REPORT_SUMMARY_TXT"
echo "" >> "$REPORT_SUMMARY_TXT"
echo "Detailed processing log: ${LOG_PROCESSING_DETAILS_TXT}" >> "$REPORT_SUMMARY_TXT"


# --- Final Summary to stdout ---
echo ""
echo "--- ${SCRIPT_MODULE_PREFIX}: Stage 1 Complete ---" >&2
echo ""
echo "--- ${SCRIPT_MODULE_PREFIX}: Final Summary ---" >&2
echo "All output files from this module are stored in the workspace directory:" >&2
echo "   ${WORKSPACE_DIR}" >&2
echo "" >&2
echo "Total SRW files found by find: $total_srw_files_from_find" >&2
echo "SRW files with a JPG counterpart by name: $potential_pairs_by_name_count" >&2
echo "SRW files processed for EXIF tags (because a JPG was found by name): $srw_processed_for_tags_count" >&2
echo "SRW files (from pairs) missing essential tags or DateTime conversion error: $srw_missing_tags_count" >&2
echo "JPG files (from pairs) missing essential tags or DateTime conversion error: $jpg_missing_tags_count" >&2
echo "DateTime conversion errors (total for SRW+JPG in pairs): $datetime_conversion_errors" >&2
echo "Pairs with mandatory EXIF tag mismatches (Model or DateTime outside tolerance): $tag_mismatch_count" >&2
echo "JPG files successfully verified and moved: $moved_jpg_count" >&2
echo "Errors encountered while moving JPG files: $error_moving_count" >&2
echo "" >&2
echo "Detailed processing log: ${LOG_PROCESSING_DETAILS_TXT}" >&2
echo "Summary report: ${REPORT_SUMMARY_TXT}" >&2
echo "" >&2
echo "--- ${SCRIPT_MODULE_PREFIX}: Processing Complete ---" >&2
exit 0