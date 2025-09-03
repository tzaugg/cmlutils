#!/usr/bin/env python3
"""
CMLUtils Installation Script

This script provides an automated way to install CMLUtils from a zip file download.
It handles virtual environment creation, dependency installation, and executable setup.
"""

import os
import sys
import subprocess
import platform
import venv
from pathlib import Path


def run_command(cmd, cwd=None, capture_output=False):
    """Run a command and handle errors gracefully."""
    try:
        print(f"Running: {' '.join(cmd)}")
        result = subprocess.run(
            cmd, 
            cwd=cwd, 
            check=True, 
            capture_output=capture_output,
            text=True
        )
        if capture_output:
            return result.stdout.strip()
        return True
    except subprocess.CalledProcessError as e:
        print(f"Error running command: {' '.join(cmd)}")
        print(f"Error: {e}")
        if capture_output and e.stdout:
            print(f"Stdout: {e.stdout}")
        if capture_output and e.stderr:
            print(f"Stderr: {e.stderr}")
        return False
    except FileNotFoundError:
        print(f"Command not found: {cmd[0]}")
        return False


def check_python_version():
    """Check if Python version meets requirements."""
    version = sys.version_info
    if version.major < 3 or (version.major == 3 and version.minor < 10):
        print(f"Error: Python 3.10+ required. Current version: {version.major}.{version.minor}")
        return False
    print(f"✓ Python version {version.major}.{version.minor}.{version.micro} is compatible")
    return True


def find_python_executable():
    """Find the best Python executable to use."""
    candidates = ['python3', 'python']
    for candidate in candidates:
        try:
            result = subprocess.run(
                [candidate, '--version'], 
                capture_output=True, 
                text=True, 
                check=True
            )
            version_str = result.stdout.strip()
            print(f"Found Python: {candidate} -> {version_str}")
            return candidate
        except (subprocess.CalledProcessError, FileNotFoundError):
            continue
    return None


def create_virtual_environment(venv_path):
    """Create a virtual environment."""
    print(f"Creating virtual environment at: {venv_path}")
    try:
        venv.create(venv_path, with_pip=True)
        print("✓ Virtual environment created successfully")
        return True
    except Exception as e:
        print(f"Error creating virtual environment: {e}")
        return False


def get_venv_paths(venv_path):
    """Get the paths for the virtual environment executables."""
    if platform.system() == "Windows":
        return {
            'python': venv_path / "Scripts" / "python.exe",
            'pip': venv_path / "Scripts" / "pip.exe",
        }
    else:
        return {
            'python': venv_path / "bin" / "python",
            'pip': venv_path / "bin" / "pip",
        }


def install_package_in_venv(venv_paths, package_path):
    """Install the package in the virtual environment."""
    print("Installing cmlutils package...")
    cmd = [str(venv_paths['pip']), 'install', '-e', '.']
    return run_command(cmd, cwd=package_path)


def create_wrapper_script(venv_paths, install_dir):
    """Create a wrapper script to run cmlutil."""
    if platform.system() == "Windows":
        script_path = install_dir / "cmlutil.bat"
        script_content = f"""@echo off
"{venv_paths['python']}" -m cmlutils.cli_entrypoint %*
"""
    else:
        script_path = install_dir / "cmlutil"
        script_content = f"""#!/bin/bash
"{venv_paths['python']}" -m cmlutils.cli_entrypoint "$@"
"""
    
    try:
        with open(script_path, 'w') as f:
            f.write(script_content)
        
        if platform.system() != "Windows":
            os.chmod(script_path, 0o755)
        
        print(f"✓ Created wrapper script: {script_path}")
        return script_path
    except Exception as e:
        print(f"Error creating wrapper script: {e}")
        return None


def main():
    """Main installation function."""
    print("=" * 60)
    print("CMLUtils Installation Script")
    print("=" * 60)
    
    # Check Python version
    if not check_python_version():
        sys.exit(1)
    
    # Get current directory (should be the cmlutils project root)
    current_dir = Path.cwd()
    print(f"Installation directory: {current_dir}")
    
    # Check if we're in the right directory
    if not (current_dir / "setup.py").exists():
        print("Error: setup.py not found. Please run this script from the cmlutils project root directory.")
        sys.exit(1)
    
    # Create virtual environment
    venv_path = current_dir / "cmlutils-env"
    if venv_path.exists():
        print(f"Virtual environment already exists at: {venv_path}")
        print("Removing existing virtual environment...")
        import shutil
        shutil.rmtree(venv_path)
    
    if not create_virtual_environment(venv_path):
        sys.exit(1)
    
    # Get virtual environment paths
    venv_paths = get_venv_paths(venv_path)
    
    # Upgrade pip
    print("Upgrading pip...")
    if not run_command([str(venv_paths['pip']), 'install', '--upgrade', 'pip']):
        print("Warning: Failed to upgrade pip, continuing anyway...")
    
    # Install the package
    if not install_package_in_venv(venv_paths, current_dir):
        print("Error: Failed to install cmlutils package")
        sys.exit(1)
    
    # Create wrapper script
    wrapper_script = create_wrapper_script(venv_paths, current_dir)
    if not wrapper_script:
        print("Error: Failed to create wrapper script")
        sys.exit(1)
    
    # Test the installation
    print("Testing installation...")
    test_cmd = [str(venv_paths['python']), '-c', 'import cmlutils; print("✓ cmlutils imported successfully")']
    if not run_command(test_cmd):
        print("Error: Installation test failed")
        sys.exit(1)
    
    print("\n" + "=" * 60)
    print("Installation completed successfully!")
    print("=" * 60)
    print(f"Virtual environment: {venv_path}")
    print(f"Wrapper script: {wrapper_script}")
    print(f"\nTo use cmlutil:")
    print(f"  1. Add to PATH: export PATH={current_dir}:$PATH")
    print(f"  2. Or run directly: {wrapper_script}")
    print(f"  3. Or use: {venv_paths['python']} -m cmlutils.cli_entrypoint")
    
    print(f"\nTo test the installation:")
    print(f"  {wrapper_script} --help")
    print("\nInstallation complete!")


if __name__ == "__main__":
    main()
