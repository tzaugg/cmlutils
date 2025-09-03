#!/bin/bash
# CMLUtils Unix/Linux Installation Script
# This script provides automated installation for Unix-like systems

set -e  # Exit on any error

echo "======================================"
echo "CMLUtils Unix/Linux Installation Script"
echo "======================================"

# Check if Python is available
if ! command -v python3 &> /dev/null; then
    echo "Error: python3 is not installed or not in PATH"
    echo "Please install Python 3.10+ from your package manager or https://python.org"
    exit 1
fi

# Check Python version
python_version=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
required_version="3.10"

if [ "$(printf '%s\n' "$required_version" "$python_version" | sort -V | head -n1)" != "$required_version" ]; then
    echo "Error: Python 3.10+ required. Current version: $python_version"
    exit 1
fi

# Check if we're in the right directory
if [ ! -f "setup.py" ]; then
    echo "Error: setup.py not found"
    echo "Please run this script from the cmlutils project root directory"
    exit 1
fi

echo "Running Python installation script..."
python3 install.py

if [ $? -eq 0 ]; then
    echo ""
    echo "Installation completed successfully!"
    echo ""
    echo "To use cmlutil, you can:"
    echo "  1. Run: ./cmlutil --help"
    echo "  2. Add to PATH: export PATH=$(pwd):\$PATH"
    echo "  3. Make PATH permanent: echo 'export PATH=$(pwd):\$PATH' >> ~/.bashrc"
    echo ""
    echo "To test the installation:"
    echo "  ./cmlutil --help"
else
    echo "Installation failed. Please check the output above for details."
    exit 1
fi
