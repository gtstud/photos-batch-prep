#!/bin/bash
# Script Name: p05-gps.sh
# Description: Geotags photo/video files in 'by-date/' structure using GPX files
#              and applying a specified timezone offset to DateTimeOriginal for Geotime.

# Exit on error, treat unset variables as an error
set -e
set -u

# --- Source Common Configuration ---
# Assumes photo_workflow_config.sh is in the same directory as this script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
# shellcheck source=./photo_workflow_config.sh
source "${SCRIPT_DIR}/photo_workflow_config.sh"
# --- End Source Common Configuration ---


# --- Script-Specific Configuration ---
readonly SCRIPT_MODULE_PREFIX="p05-gps"
readonly TARGET_PROCESSING_DIR_NAME="by-date" # Directory expected to contain date-organized files
# --- End Script-Specific Configuration ---


# Ensure we're in a sane environment
LC_ALL=C
export LC_ALL

# Check for necessary commands
check_commands exiftool find mkdir wc awk grep sort echo

# --- Usage Function ---
usage() {
    echo "Usage: $(basename "$0") --timezone=<OFFSET> --gpx=<GPX_DIRECTORY_PATH>"
    echo ""
    echo "Arguments:"
    echo "  --timezone=<OFFSET>    Timezone offset for DateTimeOriginal to Geotime."
    echo "                         Examples: +2, -3, +02, -05. Assumes positive if no sign."
    echo "  --gpx=<GPX_DIR_PATH>   Path to the directory containing *.gpx files."
    echo ""
    echo "Example: $(basename "$0") --timezone=+2 --gpx=\"/path/to/my/gpx_files\""
    echo "         $(basename "$0") --timezone=-5 --gpx=\"./gpx_tracks\""
    exit 1
}

# --- Argument Parsing ---
TIMEZONE_RAW_OFFSET=""
GPX_DIR_PATH=""

if [[ $# -ne 2 ]]; then
    echo "Error: Incorrect number of arguments." >&2
    usage
fi

for arg in "$@"; do
    case "$arg" in
        --timezone=*)
        TIMEZONE_RAW_OFFSET="${arg#*=}"
        ;;
        --gpx=*)
        GPX_DIR_PATH="${arg#*=}"
        ;;
        *)
        echo "Error: Unknown option or incorrect format: $arg" >&2
        usage
        ;;
    esac
done

# Validate timezone argument format
if ! [[ "$TIMEZONE_RAW_OFFSET" =~ ^([+-]?[0-9]{1,2})$ ]]; then
    echo "Error: Invalid timezone format for --timezone. Expected format like +2, -3, 05." >&2
    echo "Received: '$TIMEZONE_RAW_OFFSET'" >&2
    usage
fi

# Validate GPX directory
if [[ -z "$GPX_DIR_PATH" ]]; then
    echo "Error: --gpx argument is missing." >&2
    usage
fi
if [[ ! -d "$GPX_DIR_PATH" ]]; then
    echo "Error: GPX directory '$GPX_DIR_PATH' does not exist or is not a directory." >&2
    usage
fi
if [[ ! -r "$GPX_DIR_PATH" ]]; then
    echo "Error: GPX directory '$GPX_DIR_PATH' is not readable." >&2
    usage
fi
# Make GPX_DIR_PATH absolute for robustness, though exiftool might handle relative paths well.
# For consistency with how other scripts use PWD, let's ensure it's clear.
# If GPX_DIR_PATH is already absolute, realpath won't change it much.
# If it's relative, it becomes absolute from PWD.
GPX_DIR_PATH_ABS="$(realpath -m "$GPX_DIR_PATH")"
if [[ ! -d "$GPX_DIR_PATH_ABS" ]]; then # Double check after realpath
    echo "Error: Resolved GPX directory '$GPX_DIR_PATH_ABS' is not valid." >&2
    exit 1
fi


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
readonly FILES_WITH_ISSUES_TXT="${WORKSPACE_DIR}/${SCRIPT_MODULE_PREFIX}-log02-files_with_issues.txt" # For files with warnings/errors

# --- Initialize Log/Report Files ---
echo "GPS Geotagging Log" > "$LOG_PROCESSING_DETAILS_TXT"
echo "Date: $(date)" >> "$LOG_PROCESSING_DETAILS_TXT"
echo "Timezone Offset for Geotime: $TIMEZONE_RAW_OFFSET" >> "$LOG_PROCESSING_DETAILS_TXT"
echo "GPX Directory: $GPX_DIR_PATH_ABS" >> "$LOG_PROCESSING_DETAILS_TXT"
echo "Target Photo Directory: ${PWD}/${TARGET_PROCESSING_DIR_NAME}" >> "$LOG_PROCESSING_DETAILS_TXT"
echo "---------------------------------------------------------------------" >> "$LOG_PROCESSING_DETAILS_TXT"
echo "" >> "$LOG_PROCESSING_DETAILS_TXT"

echo "Files with Geotagging Issues (Warnings/Errors)" > "$FILES_WITH_ISSUES_TXT"
echo "Date: $(date)" >> "$FILES_WITH_ISSUES_TXT"
echo "---------------------------------------------------------------------" >> "$FILES_WITH_ISSUES_TXT"
echo "" >> "$FILES_WITH_ISSUES_TXT"

echo "GPS Geotagging Summary Report" > "$REPORT_SUMMARY_TXT"
echo "Date: $(date)" >> "$REPORT_SUMMARY_TXT"
echo "Timezone Offset for Geotime: $TIMEZONE_RAW_OFFSET" >> "$REPORT_SUMMARY_TXT"
echo "GPX Directory: $GPX_DIR_PATH_ABS" >> "$REPORT_SUMMARY_TXT"
echo "Target Photo Directory: ${PWD}/${TARGET_PROCESSING_DIR_NAME}" >> "$REPORT_SUMMARY_TXT"
echo "---------------------------------------------------------------------" >> "$REPORT_SUMMARY_TXT"


# --- Helper Function to Format Timezone for ExifTool ---
format_exiftool_timezone_offset() {
    local tz_input="$1"
    local sign_char=""
    local hours_val
    local formatted_offset

    if [[ "${tz_input:0:1}" == "-" ]]; then
        sign_char="-"
        tz_input="${tz_input:1}"
    elif [[ "${tz_input:0:1}" == "+" ]]; then
        sign_char="+"
        tz_input="${tz_input:1}"
    else
        sign_char="+" # Default to positive if no sign
    fi

    hours_val=$(printf "%02d" "$tz_input") # Pad with zero if single digit (e.g., 2 -> 02)
    formatted_offset="${sign_char}${hours_val}:00"
    echo "$formatted_offset"
}

TIMEZONE_OFFSET_EXIFTOOL_FORMATTED=$(format_exiftool_timezone_offset "$TIMEZONE_RAW_OFFSET")
GPX_FILES_PATTERN="${GPX_DIR_PATH_ABS}/*.gpx" # Exiftool will handle the glob pattern

# --- Pre-flight Checks ---
TARGET_DIR_TO_PROCESS_REL="${PWD}/${TARGET_PROCESSING_DIR_NAME}"
if [[ ! -d "$TARGET_DIR_TO_PROCESS_REL" ]]; then
    echo "Error: Target photo directory '${TARGET_PROCESSING_DIR_NAME}' not found in the current location (${PWD})." >&2
    echo "Please ensure 'p04-by-date.sh' or a similar script has created this directory structure." >&2
    exit 1
fi

mapfile -d $'\0' gpx_file_check < <(find "$GPX_DIR_PATH_ABS" -maxdepth 1 -type f -name "*.gpx" -print0)
if [[ ${#gpx_file_check[@]} -eq 0 ]]; then
    echo "Warning: No *.gpx files found directly in '$GPX_DIR_PATH_ABS'." >&2
    echo "Warning: No *.gpx files found directly in '$GPX_DIR_PATH_ABS'. Exiftool might report an error if the pattern matches no files." >> "$LOG_PROCESSING_DETAILS_TXT"
    # Exiftool will error if -geotag pattern is empty, so we let it.
fi


# --- Main Processing Logic ---
echo ""
echo "--- ${SCRIPT_MODULE_PREFIX}: Stage 1: Geotagging Files ---" >&2
echo "Applying timezone offset '${TIMEZONE_OFFSET_EXIFTOOL_FORMATTED}' to DateTimeOriginal for Geotime." >&2
echo "Using GPX files from: '${GPX_FILES_PATTERN}'" >&2
echo "Processing files in: '${TARGET_DIR_TO_PROCESS_REL}' (recursive)" >&2

total_files_in_target_dir=0
mapfile -d $'\0' files_to_process_list < <(find "$TARGET_DIR_TO_PROCESS_REL" -type f -print0)
total_files_in_target_dir=${#files_to_process_list[@]}

if [[ $total_files_in_target_dir -eq 0 ]]; then
    echo "Target directory '${TARGET_PROCESSING_DIR_NAME}' contains no files to process. Skipping geotagging." >&2
    echo "Target directory '${TARGET_PROCESSING_DIR_NAME}' contains no files. No action taken." >> "$LOG_PROCESSING_DETAILS_TXT"
    # Initialize counts to 0 for the report
    files_geotagged_successfully_count=0
    files_unchanged_count=0
    files_with_issues_count=0
    # Proceed to summary generation
else
    echo "Found $total_files_in_target_dir files in '${TARGET_PROCESSING_DIR_NAME}' to scan for geotagging." >&2
    
    # Exiftool command construction
    # Note: \$DateTimeOriginal is used to pass literal ${DateTimeOriginal} to exiftool
    geotime_arg="-geotime<\$DateTimeOriginal${TIMEZONE_OFFSET_EXIFTOOL_FORMATTED}"
    exiftool_cmd_array=(
        exiftool
        -overwrite_original # Modifies files in place
        -P                  # Preserve filesystem modification date/time
        "$geotime_arg"
        -geotag "$GPX_FILES_PATTERN"
        -r                  # Recurse into subdirectories
        "$TARGET_DIR_TO_PROCESS_REL"
    )

    echo "Executing Exiftool command:" >> "$LOG_PROCESSING_DETAILS_TXT"
    # Log the command carefully, handling spaces in arguments if any by quoting elements
    printf " " >> "$LOG_PROCESSING_DETAILS_TXT" # Initial space for readability
    for token in "${exiftool_cmd_array[@]}"; do
        if [[ "$token" == *' '* ]]; then
            printf "'%s' " "$token" >> "$LOG_PROCESSING_DETAILS_TXT"
        else
            printf "%s " "$token" >> "$LOG_PROCESSING_DETAILS_TXT"
        fi
    done
    printf "\n\n" >> "$LOG_PROCESSING_DETAILS_TXT"


    echo "Starting Exiftool... (This may take a while for many files)" >&2
    # Capture stdout and stderr together, then the exit code
    exiftool_output_full=$( "${exiftool_cmd_array[@]}" 2>&1 )
    exiftool_exit_code=$?
    echo "Exiftool processing finished. Exit code: $exiftool_exit_code" >&2

    echo "--- Exiftool Raw Output (Exit Code: $exiftool_exit_code) ---" >> "$LOG_PROCESSING_DETAILS_TXT"
    echo "$exiftool_output_full" >> "$LOG_PROCESSING_DETAILS_TXT"
    echo "--- End Exiftool Raw Output ---" >> "$LOG_PROCESSING_DETAILS_TXT"


    # Parse Exiftool output for counts and issues
    files_geotagged_successfully_count=0
    files_unchanged_count=0
    
    # Get count of successfully updated files from summary line
    summary_line_updated=$(echo "$exiftool_output_full" | grep -Eom1 "^[[:space:]]*[0-9]+ image files updated$")
    if [[ -n "$summary_line_updated" ]]; then
        files_geotagged_successfully_count=$(echo "$summary_line_updated" | awk '{print $1}')
    fi

    # Get count of unchanged files from summary line
    summary_line_unchanged=$(echo "$exiftool_output_full" | grep -Eom1 "^[[:space:]]*[0-9]+ image files unchanged$")
    if [[ -n "$summary_line_unchanged" ]]; then
        files_unchanged_count=$(echo "$summary_line_unchanged" | awk '{print $1}')
    fi
    
    # Check for critical error: GPX files not found by pattern
    if echo "$exiftool_output_full" | grep -qE "Error: File not found - ${GPX_DIR_PATH_ABS}/\*\.gpx"; then
        echo "CRITICAL ERROR: Exiftool reported that no GPX files were found using the pattern '${GPX_FILES_PATTERN}'." >&2
        echo "CRITICAL ERROR from Exiftool: No GPX files found matching pattern '${GPX_FILES_PATTERN}'." >> "$FILES_WITH_ISSUES_TXT"
        # This often means no files were updated due to this, so counts might be 0.
    fi

    # Log specific file warnings/errors
    # Using awk for more robust parsing of lines containing file paths
    echo "$exiftool_output_full" | awk -v logfile="$FILES_WITH_ISSUES_TXT" '
        /Warning: No writable tags set from .* for '\''/ || \
        /Warning: No matching GPS fix for '\''/ || \
        /Warning: Tag '\''DateTimeOriginal'\'' not defined for '\''/ || \
        /Error: .* - / {
            # Extract filename path, which is usually at the end or in quotes
            filepath = ""
            if (match($0, /for '\''([^'\'']+'\''?'')'\''$/)) { # "for 'path/file.jpg'"
                filepath = substr($0, RSTART + 5, RLENGTH - 6)
            } else if (match($0, /Error: .* - (.*)$/)) { # "Error: Some error - path/file.jpg"
                filepath = substr($0, RSTART + length("Error: .* - "))
            } else if (match($0, /Not a valid .* file - (.*)$/)) { # "Error: Not a valid XXX file - path/file.jpg"
                 filepath = substr($0, RSTART + length("Not a valid XXX file - "))
            }


            if (filepath != "") {
                # Remove potential leading/trailing whitespace from extracted path
                gsub(/^[ \t]+|[ \t]+$/, "", filepath)
                print "File: " filepath " // Issue: " $0 >> logfile
            } else {
                # General warning/error not easily parsable for a filename
                print "General Issue: " $0 >> logfile
            }
        }
    '
    # Count unique files with issues (ensure file exists and has content first)
    files_with_issues_count=0
    if [[ -s "$FILES_WITH_ISSUES_TXT" ]]; then
        # Count lines that start with "File: " to get a count of file-specific issues
        # This might overcount if a file has multiple distinct logged issues by awk,
        # or undercount if awk couldn't extract filename.
        # A more robust way is to count unique filenames:
        files_with_issues_count=$(awk -F' // Issue: ' '/^File: / {print $1}' "$FILES_WITH_ISSUES_TXT" | sort -u | wc -l)
    fi
    if [[ $files_with_issues_count -gt 0 ]]; then
         echo "Found $files_with_issues_count file(s) with warnings or errors. See: ${FILES_WITH_ISSUES_TXT}" >&2
    fi
fi # End of if total_files_in_target_dir -eq 0

echo "--- ${SCRIPT_MODULE_PREFIX}: Stage 1 Complete ---" >&2
echo "" >&2


# --- Generate Summary Report ---
echo "--- ${SCRIPT_MODULE_PREFIX}: Generating Summary Report ---" >&2
echo "" >> "$REPORT_SUMMARY_TXT"
echo "Geotagging Summary:" >> "$REPORT_SUMMARY_TXT"
echo "-------------------" >> "$REPORT_SUMMARY_TXT"
echo "Total files scanned in '${TARGET_PROCESSING_DIR_NAME}': $total_files_in_target_dir" >> "$REPORT_SUMMARY_TXT"
echo "Files successfully geotagged (tags updated): $files_geotagged_successfully_count" >> "$REPORT_SUMMARY_TXT"
echo "Files unchanged by Exiftool (e.g., no GPS match, already tagged): $files_unchanged_count" >> "$REPORT_SUMMARY_TXT"
echo "Files with specific warnings or errors during processing: $files_with_issues_count" >> "$REPORT_SUMMARY_TXT"
if [[ $files_with_issues_count -gt 0 ]]; then
    echo "  (Details for these files are in: ${FILES_WITH_ISSUES_TXT})" >> "$REPORT_SUMMARY_TXT"
fi
echo "" >> "$REPORT_SUMMARY_TXT"
echo "Detailed processing log (including full Exiftool output): ${LOG_PROCESSING_DETAILS_TXT}" >> "$REPORT_SUMMARY_TXT"
echo "--- ${SCRIPT_MODULE_PREFIX}: Summary Report Generation Complete ---" >&2
echo "" >&2


# --- Final Summary to stdout ---
echo "--- ${SCRIPT_MODULE_PREFIX}: Final Summary ---" >&2
echo "All output files from this module are stored in the workspace directory:" >&2
echo "   ${WORKSPACE_DIR}" >&2
echo "" >&2
echo "Total files scanned in '${TARGET_PROCESSING_DIR_NAME}': $total_files_in_target_dir" >&2
echo "Files successfully geotagged (tags updated): $files_geotagged_successfully_count" >&2
echo "Files unchanged by Exiftool (e.g., no GPS match, already tagged): $files_unchanged_count" >&2
echo "Files with specific warnings or errors during processing: $files_with_issues_count" >&2
if [[ $files_with_issues_count -gt 0 ]]; then
    echo "  -> Details for these files are in: ${FILES_WITH_ISSUES_TXT}" >&2
fi
echo "" >&2
echo "Detailed processing log: ${LOG_PROCESSING_DETAILS_TXT}" >&2
echo "Summary report: ${REPORT_SUMMARY_TXT}" >&2
echo "" >&2
echo "--- ${SCRIPT_MODULE_PREFIX}: Processing Complete ---" >&2
exit 0