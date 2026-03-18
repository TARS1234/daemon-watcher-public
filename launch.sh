#!/bin/bash
# Daemon Watcher - macOS/Linux Launcher
# Double-click this file to start the setup wizard

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Run the wizard
python3 install_wizard_standalone.py
