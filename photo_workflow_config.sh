#!/bin/bash

# This file contains common configurations for the photo processing workflow.
# It should be sourced by individual processing scripts.

# --- Global Workspace Configuration ---
# All processing scripts will use this single directory for their outputs.
# The underscore prefix helps keep it at the top of directory listings.
readonly GLOBAL_WORKSPACE_DIR_NAME="_photo_workspace"

# --- Common Variables & Functions (add more as needed) ---
readonly SEP=$'\t' # Standard field separator for TSV files

# Function to ensure critical commands are available
check_commands() {
    for cmd in "$@"; do
        if ! command -v "$cmd" &> /dev/null; then
            echo "Error: Required command '$cmd' not found. Please install it." >&2
            exit 1
        fi
    done
}

# You could add more common functions here, e.g., for logging, error handling, etc.

# --- End of Common Configurations ---