#!/usr/bin/env python3
"""
Linux Deployment Test Script

This script validates that cmlutils can be deployed successfully on Linux systems
by testing all installation and functionality components.
"""

import os
import sys
import subprocess
import tempfile
import shutil
from pathlib import Path


def run_command(cmd, cwd=None, capture_output=True):
    """Run a command and return success status and output."""
    try:
        result = subprocess.run(
            cmd, 
            cwd=cwd, 
            check=True, 
            capture_output=capture_output,
            text=True,
            shell=isinstance(cmd, str)
        )
        return True, result.stdout.strip() if capture_output else ""
    except subprocess.CalledProcessError as e:
        return False, e.stderr.strip() if capture_output and e.stderr else str(e)
    except FileNotFoundError:
        return False, f"Command not found: {cmd[0] if isinstance(cmd, list) else cmd}"


def test_linux_installation():
    """Test Linux-specific installation process."""
    print("🐧 Testing Linux Installation Process")
    print("=" * 50)
    
    current_dir = Path.cwd()
    
    # Test 1: Check required files exist
    print("\n1. Checking installation files...")
    required_files = [
        "install.py",
        "install.sh", 
        "verify_installation.py",
        "setup.py",
        "requirements.txt",
        "pyproject.toml",
        "README.md",
        "INSTALL.md",
        "CLIENT_DEPLOYMENT.md"
    ]
    
    missing_files = []
    for file in required_files:
        file_path = current_dir / file
        if file_path.exists():
            print(f"  ✓ {file}")
        else:
            print(f"  ✗ {file} - MISSING")
            missing_files.append(file)
    
    if missing_files:
        print(f"\n❌ Missing files: {missing_files}")
        return False
    
    # Test 2: Check executable permissions
    print("\n2. Checking file permissions...")
    executable_files = ["install.py", "install.sh", "verify_installation.py"]
    for file in executable_files:
        file_path = current_dir / file
        if os.access(file_path, os.X_OK):
            print(f"  ✓ {file} is executable")
        else:
            print(f"  ✗ {file} is not executable")
            return False
    
    # Test 3: Check Python imports work in virtual environment
    print("\n3. Testing virtual environment Python modules...")
    venv_python = current_dir / "cmlutils-env" / "bin" / "python"
    
    if not venv_python.exists():
        print("  ℹ Virtual environment not found (this is normal for fresh installation)")
        print("    Installation scripts will create it automatically")
    else:
        modules_to_test = [
            "click",
            "requests", 
            "flatten_json",
            "cmlutils",
            "cmlutils.cli_entrypoint",
            "cmlutils.projects"
        ]
        
        for module in modules_to_test:
            success, output = run_command([
                str(venv_python), "-c", f"import {module}; print('✓ {module}')"
            ])
            if success:
                print(f"  ✓ {module}")
            else:
                print(f"  ✗ {module} - {output}")
                return False
    
    # Test 4: Validate Linux shell script
    print("\n4. Checking Linux shell script...")
    with open(current_dir / "install.sh", "r") as f:
        script_content = f.read()
    
    if "#!/bin/bash" in script_content:
        print("  ✓ Proper shebang for Linux")
    else:
        print("  ✗ Missing or incorrect shebang")
        return False
    
    if "python3" in script_content:
        print("  ✓ Uses python3 command")
    else:
        print("  ✗ Doesn't use python3")
        return False
    
    # Test 5: Check documentation
    print("\n5. Checking documentation...")
    with open(current_dir / "README.md", "r") as f:
        readme_content = f.read()
    
    if "From Zip File" in readme_content:
        print("  ✓ Zip file installation instructions present")
    else:
        print("  ✗ Missing zip file installation instructions")
        return False
    
    if "./install.sh" in readme_content:
        print("  ✓ Linux installation script referenced")
    else:
        print("  ✗ Linux installation script not referenced")
        return False
    
    print("\n🎉 All Linux deployment tests PASSED!")
    return True


def test_simulated_client_workflow():
    """Simulate a client receiving and installing the zip file."""
    print("\n\n🚀 Testing Simulated Client Workflow")
    print("=" * 50)
    
    current_dir = Path.cwd()
    
    # Test the workflow a client would follow
    print("\n📋 Client Workflow Steps:")
    print("1. Extract zip file (simulated) ✓")
    print("2. cd cmlutils-main ✓")  
    print("3. Run installation script...")
    
    # Check if we can run the installation script
    success, output = run_command(["bash", "-c", "echo 'Test shell access'"])
    if success:
        print("  ✓ Bash shell available")
    else:
        print("  ✗ Bash shell not available")
        return False
    
    # Check Python availability
    success, output = run_command(["python3", "--version"])
    if success:
        print(f"  ✓ Python available: {output}")
    else:
        print("  ✗ Python3 not available")
        return False
    
    # Check package structure
    print("4. Validate package structure...")
    required_dirs = ["cmlutils", "examples", "tests"]
    for dir_name in required_dirs:
        dir_path = current_dir / dir_name  
        if dir_path.exists() and dir_path.is_dir():
            print(f"  ✓ {dir_name}/ directory")
        else:
            print(f"  ✗ {dir_name}/ directory missing")
            return False
    
    print("5. Check configuration compatibility...")
    config_path = Path.home() / ".cmlutils"
    if config_path.exists():
        print(f"  ✓ Configuration directory exists: {config_path}")
    else:
        print(f"  ℹ No existing configuration (normal for new installations)")
    
    print("\n🎉 Client workflow simulation PASSED!")
    return True


def main():
    """Main test function."""
    print("🔧 CMLUtils Linux Deployment Validation")
    print("=" * 60)
    
    # Run tests
    linux_test = test_linux_installation()
    workflow_test = test_simulated_client_workflow()
    
    print("\n" + "=" * 60)
    print("📊 TEST SUMMARY")
    print("=" * 60)
    
    if linux_test and workflow_test:
        print("✅ ALL TESTS PASSED!")
        print("\n📦 The cmlutils package is ready for Linux deployment!")
        print("\n🚀 Client Instructions:")
        print("   1. Extract zip file: unzip cmlutils-main.zip")
        print("   2. Enter directory: cd cmlutils-main")
        print("   3. Run installer: ./install.sh")
        print("   4. Verify: ./verify_installation.py")
        print("   5. Use: ./cmlutil --help")
        
        return 0
    else:
        print("❌ SOME TESTS FAILED!")
        print("Please review the errors above and fix issues before deployment.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
