#!/usr/bin/env python3
"""
CMLUtils Installation Verification Script

This script verifies that cmlutils has been installed correctly and all
components are working as expected.
"""

import os
import sys
import subprocess
from pathlib import Path


def run_command(cmd, cwd=None, capture_output=True):
    """Run a command and return success status and output."""
    try:
        result = subprocess.run(
            cmd, 
            cwd=cwd, 
            check=True, 
            capture_output=capture_output,
            text=True
        )
        return True, result.stdout.strip() if capture_output else ""
    except subprocess.CalledProcessError as e:
        return False, e.stderr.strip() if capture_output and e.stderr else str(e)
    except FileNotFoundError:
        return False, f"Command not found: {cmd[0]}"


def check_file_exists(file_path, description):
    """Check if a file exists and report status."""
    if Path(file_path).exists():
        print(f"✓ {description}: {file_path}")
        return True
    else:
        print(f"✗ {description} not found: {file_path}")
        return False


def main():
    """Main verification function."""
    print("=" * 60)
    print("CMLUtils Installation Verification")
    print("=" * 60)
    
    current_dir = Path.cwd()
    print(f"Checking installation in: {current_dir}")
    
    all_checks_passed = True
    
    # 1. Check virtual environment
    venv_path = current_dir / "cmlutils-env"
    if check_file_exists(venv_path, "Virtual environment"):
        # Check Python executable in venv
        if sys.platform == "win32":
            python_exe = venv_path / "Scripts" / "python.exe"
        else:
            python_exe = venv_path / "bin" / "python"
        
        check_file_exists(python_exe, "Virtual environment Python")
    else:
        all_checks_passed = False
    
    # 2. Check wrapper script
    if sys.platform == "win32":
        wrapper_script = current_dir / "cmlutil.bat"
    else:
        wrapper_script = current_dir / "cmlutil"
    
    if not check_file_exists(wrapper_script, "Wrapper script"):
        all_checks_passed = False
    
    # 3. Test Python import
    print("\n" + "=" * 40)
    print("Testing Python imports...")
    print("=" * 40)
    
    success, output = run_command([
        str(python_exe), 
        "-c", 
        "import cmlutils; print('cmlutils version:', cmlutils.__version__ if hasattr(cmlutils, '__version__') else 'unknown')"
    ])
    
    if success:
        print(f"✓ Python import test: {output}")
    else:
        print(f"✗ Python import failed: {output}")
        all_checks_passed = False
    
    # 4. Test CLI entry point
    print("\n" + "=" * 40)
    print("Testing CLI entry point...")
    print("=" * 40)
    
    success, output = run_command([str(python_exe), "-m", "cmlutils.cli_entrypoint", "--help"])
    
    if success:
        print("✓ CLI entry point test passed")
        print("First few lines of help:")
        for line in output.split('\n')[:5]:
            print(f"  {line}")
    else:
        print(f"✗ CLI entry point failed: {output}")
        all_checks_passed = False
    
    # 5. Test wrapper script
    print("\n" + "=" * 40)
    print("Testing wrapper script...")
    print("=" * 40)
    
    success, output = run_command([str(wrapper_script), "--help"])
    
    if success:
        print("✓ Wrapper script test passed")
    else:
        print(f"✗ Wrapper script failed: {output}")
        all_checks_passed = False
    
    # 6. Test project commands
    print("\n" + "=" * 40)
    print("Testing project commands...")
    print("=" * 40)
    
    success, output = run_command([str(wrapper_script), "project", "--help"])
    
    if success:
        print("✓ Project commands available")
    else:
        print(f"✗ Project commands failed: {output}")
        all_checks_passed = False
    
    # 7. Check configuration directory
    config_dir = Path.home() / ".cmlutils"
    if config_dir.exists():
        print(f"✓ Configuration directory exists: {config_dir}")
        
        # List config files if any
        config_files = list(config_dir.glob("*.ini"))
        if config_files:
            print("  Configuration files found:")
            for config_file in config_files:
                print(f"    - {config_file.name}")
        else:
            print("  No configuration files found (this is normal for new installations)")
    else:
        print(f"ℹ Configuration directory not found: {config_dir} (will be created when needed)")
    
    # Summary
    print("\n" + "=" * 60)
    if all_checks_passed:
        print("✅ All verification checks PASSED!")
        print("CMLUtils is properly installed and ready to use.")
        print(f"\nTo use cmlutils:")
        print(f"  • Run: {wrapper_script}")
        print(f"  • Or add to PATH: export PATH={current_dir}:$PATH")
        print(f"  • Then use: cmlutil --help")
    else:
        print("❌ Some verification checks FAILED!")
        print("Please review the errors above and retry installation.")
        return 1
    
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
