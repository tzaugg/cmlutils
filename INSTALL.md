# CMLUtils Installation Guide

This guide provides comprehensive installation instructions for CMLUtils, including installation from zip files, git repositories, and development setups.

## Quick Start (Zip File Installation)

If you received cmlutils as a zip file, follow these steps:

### 1. Extract and Navigate
```bash
unzip cmlutils-main.zip
cd cmlutils-main
```

### 2. Automated Installation
Run the automated installation script:

```bash
python3 install.py
```

This script will:
- Check Python version compatibility (requires Python 3.10+)
- Create a virtual environment (`cmlutils-env/`)
- Install all dependencies
- Install cmlutils in editable mode
- Create a `cmlutil` wrapper script
- Test the installation

### 3. Add to PATH (Optional)
To use `cmlutil` from anywhere:

**Linux/macOS:**
```bash
export PATH=$(pwd):$PATH
echo 'export PATH='$(pwd)':$PATH' >> ~/.bashrc  # Make permanent
```

**Windows:**
Add the current directory to your system PATH environment variable.

### 4. Test Installation
```bash
./cmlutil --help
```

## Alternative Installation Methods

### Manual Installation from Zip

If the automated script doesn't work for your environment:

1. **Create virtual environment:**
```bash
python3 -m venv cmlutils-env
```

2. **Activate virtual environment:**

**Linux/macOS:**
```bash
source cmlutils-env/bin/activate
```

**Windows:**
```bash
cmlutils-env\Scripts\activate
```

3. **Install dependencies and package:**
```bash
pip install --upgrade pip
pip install -e .
```

4. **Test installation:**
```bash
cmlutil --help
```

### Installation from Git Repository

**From main branch:**
```bash
python3 -m pip install git+https://github.com/cloudera/cmlutils@main
```

**From specific branch:**
```bash
python3 -m pip install git+https://github.com/cloudera/cmlutils@<branch-name>
```

### Development Installation

For development work:

1. **Clone repository:**
```bash
git clone https://github.com/cloudera/cmlutils.git
cd cmlutils
```

2. **Create and activate virtual environment:**
```bash
python3 -m venv cmlutils-env
source cmlutils-env/bin/activate  # Linux/macOS
# or
cmlutils-env\Scripts\activate     # Windows
```

3. **Install in editable mode:**
```bash
pip install --upgrade pip
pip install -e .
```

4. **Install development tools (optional):**
```bash
pip install black isort
```

## System Requirements

- **Python**: 3.10 or higher
- **Operating System**: Linux, macOS, or Windows
- **Dependencies**: Automatically installed via pip
  - click >= 8.1.3
  - flatten-json >= 0.1.13
  - requests >= 2.30.0

## Troubleshooting

### Common Issues

**1. Python Version Error**
```
Error: Python 3.10+ required. Current version: 3.x
```
**Solution:** Install Python 3.10 or higher from [python.org](https://python.org)

**2. Permission Denied**
```
PermissionError: [Errno 13] Permission denied
```
**Solution:** Use `sudo` on Linux/macOS or run as administrator on Windows

**3. Module Not Found**
```
ModuleNotFoundError: No module named 'cmlutils'
```
**Solution:** Ensure virtual environment is activated and package is installed

**4. Command Not Found: cmlutil**
```bash
cmlutil: command not found
```
**Solutions:**
- Use full path: `./cmlutil --help`
- Add to PATH: `export PATH=$(pwd):$PATH`
- Use Python module: `python -m cmlutils.cli_entrypoint --help`

### Virtual Environment Issues

If virtual environment creation fails:

1. **Update pip and setuptools:**
```bash
python3 -m pip install --upgrade pip setuptools
```

2. **Use system Python:**
```bash
/usr/bin/python3 -m venv cmlutils-env
```

3. **Clear Python cache:**
```bash
python3 -c "import sys; print(sys.path)"
```

### Network/SSL Issues

If you encounter SSL certificate errors:

1. **Update certificates:**
```bash
pip install --upgrade certifi
```

2. **Use trusted hosts (temporary fix):**
```bash
pip install --trusted-host pypi.org --trusted-host pypi.python.org -e .
```

## Verification

After installation, verify everything works:

1. **Check version:**
```bash
cmlutil --version
```

2. **List available commands:**
```bash
cmlutil --help
```

3. **Test project commands:**
```bash
cmlutil project --help
```

## Configuration

CMLUtils uses configuration files located in `~/.cmlutils/`:

- `export-config.ini` - For export operations
- `import-config.ini` - For import operations

Example configuration:
```ini
[DEFAULT]
url=https://your-cml-workspace.com
ca_path=False
username=admin
apiv1_key=your_api_key_here

[project_name]
username=admin
apiv1_key=your_api_key_here
source_dir=/path/to/exports
output_dir=/tmp/cmlutils-logs
```

## Uninstallation

To remove cmlutils:

1. **Deactivate virtual environment:**
```bash
deactivate
```

2. **Remove installation directory:**
```bash
rm -rf cmlutils-main/
```

3. **Remove from PATH (if added):**
Edit your shell configuration file (`~/.bashrc`, `~/.zshrc`, etc.) and remove the PATH entry.

## Support

For issues and questions:
- **GitHub Issues**: Report bugs at https://github.com/cloudera/cmlutils/issues
- **Security Issues**: Email security@cloudera.com
- **Documentation**: Visit the [GitHub wiki](https://github.com/cloudera/cmlutils/wiki)
