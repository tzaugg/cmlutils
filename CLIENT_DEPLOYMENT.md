# CMLUtils Client Deployment Guide

This guide is for clients who have received the CMLUtils package as a zip file and need to install and use it.

## Quick Start

1. **Extract the zip file:**
   ```bash
   unzip cmlutils-main.zip
   cd cmlutils-main
   ```

2. **Choose your installation method:**

   **Option A: Automatic (Recommended)**
   ```bash
   # For Unix/Linux/macOS
   ./install.sh
   ```

   **Option B: Manual**
   ```bash
   python3 -m venv cmlutils-env
   source cmlutils-env/bin/activate  # Linux/macOS
   # OR cmlutils-env\Scripts\activate  # Windows
   pip install -e .
   ```

3. **Verify installation:**
   ```bash
   python3 verify_installation.py
   ```

4. **Use CMLUtils:**
   ```bash
   ./cmlutil --help
   ```

## System Requirements

- **Python 3.10 or higher** (required)
- **Internet connection** (for dependency installation)
- **Disk space**: ~50MB for virtual environment and dependencies

## Troubleshooting

### Python Version Issues
If you see "Python 3.10+ required":
- **Linux/macOS**: Install via package manager or from python.org
- **Windows**: Download from [python.org](https://python.org)

### Permission Issues
If you get permission errors:
- **Linux/macOS**: Try `sudo` or check file permissions
- **Windows**: Run as Administrator

### Network/SSL Issues
If pip installation fails:
```bash
pip install --trusted-host pypi.org --trusted-host pypi.python.org -e .
```

## What Gets Installed

The installation process:
1. Creates a virtual environment (`cmlutils-env/`)
2. Installs Python dependencies (click, requests, flatten-json)
3. Installs cmlutils in editable mode
4. Creates executable wrapper scripts (`cmlutil` or `cmlutil.bat`)

## Configuration

After installation, configure CMLUtils by creating configuration files in `~/.cmlutils/`:

### export-config.ini
```ini
[DEFAULT]
url=https://your-source-cml-workspace.com
ca_path=False
username=your_username
apiv2_key=your_v2_api_key
# For backward compatibility: apiv1_key=your_v1_api_key

[project_name]
username=your_username
apiv2_key=your_v2_api_key
source_dir=/path/to/export/directory
output_dir=/tmp/cmlutils-export-logs
```

### import-config.ini
```ini
[DEFAULT]
url=https://your-target-cml-workspace.com
ca_path=False
username=your_username
apiv2_key=your_v2_api_key
# For backward compatibility: apiv1_key=your_v1_api_key

[project_name]
username=your_username
apiv2_key=your_v2_api_key
source_dir=/path/to/import/directory
output_dir=/tmp/cmlutils-import-logs
```

## Basic Usage

### Export a project
```bash
./cmlutil project export --project_name my_project --verbose
```

### Import a project
```bash
./cmlutil project import --project_name my_project --verify --verbose
```

### Validate migration
```bash
./cmlutil project validate-migration --project_name my_project --verbose
```

### Get help
```bash
./cmlutil --help
./cmlutil project --help
```

## Support

For technical support:
- **GitHub Issues**: https://github.com/cloudera/cmlutils/issues
- **Documentation**: https://github.com/cloudera/cmlutils/wiki
- **Security Issues**: security@cloudera.com

## Files in This Package

- `install.sh` - Unix/Linux installation script
- `verify_installation.py` - Installation verification script
- `setup.py` - Package setup configuration
- `requirements.txt` - Python dependencies
- `README.md` - Detailed documentation
- `INSTALL.md` - Complete installation guide
- `cmlutils/` - Main package source code

## Uninstallation

To remove cmlutils:
1. Delete the installation directory: `rm -rf cmlutils-main/`
2. Remove from PATH if added
3. Delete configuration: `rm -rf ~/.cmlutils/` (optional)
