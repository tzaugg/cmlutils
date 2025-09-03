# **cmlutil** 

`cmlutil` is a command-line interface (CLI) tool designed to enhance the [Cloudera Machine Learning (CML)](https://docs.cloudera.com/machine-learning/cloud/index.html) experience. It provides various utilities and functionalities to help working with Cloudera Machine Learning.

`cmlutil project` command helps to migrate a CDSW/CML [projects](https://docs.cloudera.com/machine-learning/cloud/projects/index.html)
(along with associated assets like [models](https://docs.cloudera.com/machine-learning/cloud/models/index.html),
[jobs](https://docs.cloudera.com/machine-learning/cloud/jobs-pipelines/index.html) and [applications](https://docs.cloudera.com/machine-learning/cloud/applications/index.html))
to another CML workspace. This tool aims to solve for migrating projects from legacy CDSW clusters (which will be EOL'd soon)
to CML public cloud/private cloud. The tool uses the host it is running on as its "scratch space" for temporarily holding project
data and metadata before the project is fully migrated to the target CML workspace. This host is interchangeably referred to as "Bastion host" or "local machine" in this document.
## CML Project migration documentation
The comprehensive documentation for project migration can be located within the [GitHub wiki page](https://github.com/cloudera/cmlutils/wiki).

## Enhanced Logging and Verbose Mode

CMLutils now supports enhanced logging with a `--verbose` flag to provide detailed visibility into API calls, file transfers, and migration operations.

### Usage

Add the `--verbose` flag to any project command to enable detailed logging:

```bash
# Export with verbose logging
cmlutil project export --project_name my_project --verbose

# Import with verbose logging  
cmlutil project import --project_name my_project --verbose

# Import with verification and verbose logging
cmlutil project import --project_name my_project --verify --verbose

# Validate migration with verbose logging
cmlutil project validate-migration --project_name my_project --verbose
```

### Logging Levels

**Normal Mode (default):**
- INFO level logging
- Basic operation status and progress
- Error messages and warnings
- Success/failure notifications

**Verbose Mode (`--verbose` flag):**
- DEBUG level logging (includes all normal mode logging)
- **API Call Details**: HTTP method, URL, request/response bodies, timing
- **File Transfer Details**: Source/destination paths, rsync commands, retry attempts
- **Migration Progress**: Model/job/application creation steps, runtime selection logic
- **Performance Metrics**: Operation timing and API response times

### What Verbose Mode Shows

#### API Call Logging
```
DEBUG: API v1 Request: GET https://workspace.apps.cloudera.com/api/v1/users/admin
DEBUG: API v1 Request Body: {"expiryDate": "2025-09-10T10:07:07Z"}
DEBUG: API v1 Response: https://workspace.apps.cloudera.com/api/v1/users/admin (Status: 200, Time: 0.45s)
DEBUG: API v1 Response Body: {"id": 1, "username": "admin", "admin": true, "api_key_expiry_date": "2026-09-03T07:00:00.000Z"...}
```

#### File Transfer Logging  
```
INFO: SSH connection successful
DEBUG: Transfer details - Source: /Users/export/CDV/project-data/, Destination: cdsw@localhost:/home/cdsw/, SSH Port: 7468
DEBUG: Using exclude file: None
DEBUG: Retry limit set to: 3
DEBUG: Rsync attempt 1 of 3
DEBUG: Executing rsync command: rsync --delete -P -r -v -i -a -e ssh -p 7468 -oStrictHostKeyChecking=no...
INFO: Project files transferred successfully
```

#### Migration Progress
```
INFO: Started importing project: CDV
INFO: Begin validating for import.
INFO: Rsync enabled runtime is available.
INFO: Finished validating import validations for project CDV.
DEBUG: Starting model creation process for project_id: 9k62-9az5-7c1t-rasa
DEBUG: Found 0 models to import
INFO: Skipping the already existing application CDV 1 with same subdomain- cdvapp
INFO: Models are not present in the project CDV.
SUCCESS: Import of Project CDV Successful
```

### Success Output Examples

#### Export Success
```
SUCCESS: Export of Project CDV Successful 
        Exported 0 Jobs []
        Exported 0 Models []
        Exported 1 Applications ['CDV 1']
CDV Export took 27.64 seconds
```

#### Import Success
```
SUCCESS: Import of Project CDV Successful 
        Imported 0 Jobs []
        Imported 0 Models []
        Imported 1 Applications ['CDV 1']
CDV Import took 30.75 seconds
```

### Benefits

- **Troubleshooting**: See exactly which API calls fail and why
- **Performance Monitoring**: Identify slow operations with timing data  
- **Debugging**: Track file transfer issues and retry logic
- **Transparency**: Understand what the tool is doing at each step
- **Audit Trail**: Complete log of all API interactions for compliance
- **Real-time Feedback**: Monitor file transfer progress and connection status

### SSL/TLS Certificate Configuration

CMLutils supports flexible SSL/TLS certificate verification options for different CML workspace environments.

#### Certificate Path Options

In your configuration files (`export-config.ini` and `import-config.ini`), the `ca_path` parameter supports:

1. **Valid Certificate Path**: Point to your certificate bundle
   ```ini
   ca_path=/opt/cml/cert.pem
   ```

2. **System Default**: Use system certificate store  
   ```ini
   ca_path=
   ```

3. **Disable SSL Verification**: Skip certificate verification (for testing environments)
   ```ini
   ca_path=False
   ```

#### Disabling SSL Verification

When `ca_path=False` is set, cmlutils will:
- Skip SSL certificate verification for all API calls
- Add `--insecure-skip-verify` flag to cdswctl operations  
- Display security warnings about unverified HTTPS requests
- Continue operations even with invalid/self-signed certificates

**Example Configuration:**
```ini
[DEFAULT]
url=https://cml-workspace.example.com
ca_path=False
username=admin
apiv1_key=your_api_key_here

[my_project]
username=admin
apiv1_key=your_api_key_here
```

#### Security Warning

**Important**: Setting `ca_path=False` disables SSL certificate verification, which reduces security. This should only be used in:
- Testing/development environments
- Internal networks with self-signed certificates
- Temporary troubleshooting scenarios

For production environments, always use proper SSL certificates and set `ca_path` to your certificate bundle path.

#### Verbose Mode SSL Logging

With `--verbose` flag enabled, you'll see detailed SSL handling:
```
DEBUG: Added --insecure-skip-verify flag to cdswctl login command
WARNING: InsecureRequestWarning: Unverified HTTPS request is being made to host 'workspace.example.com'
INFO: Login succeeded
```

## Installation

### From Zip File (Recommended for Client Deployments)

If you received cmlutils as a zip file, this is the easiest installation method:

1. **Extract the zip file:**
```bash
unzip cmlutils-main.zip
cd cmlutils-main
```

2. **Run the automated installer:**
```bash
./install.sh
```

The installer will:
- Check Python 3.10+ compatibility
- Create a virtual environment
- Install all dependencies
- Create the `cmlutil` command
- Test the installation

3. **Add to PATH (optional):**
```bash
export PATH=$(pwd):$PATH
```

4. **Test installation:**
```bash
./cmlutil --help
```

> 📖 **For detailed installation instructions and troubleshooting, see [INSTALL.md](INSTALL.md)**

### Development mode
1. Clone the repo and run `python3 -m pip install --editable .` .
2. Check if the command `cmlutil` is running or not.
3. By installing the CLI in editable mode, any changes done to the source code would reflect in real-time without the need for re-installing again.

### For production
1. To install from `main` branch:
```
python3 -m pip install git+https://github.com/cloudera/cmlutils@main
```
2. Or from a feature or release branch:
```
python3 -m pip install git+https://github.com/cloudera/cmlutils@<branch-name>
```
## Development Guidelines
* We use two formatting tools, namely `black` and `isort` to format our python repo. Please run these commands before commiting any changes. `isort` helps arranging the imports in a logical manner.
  * They can be installed using `python3 -m pip install black isort`.
  * Run `black .` while inside the root directory.
  * Run `isort --profile black .`.

## Reporting bugs and vulnerabilities

 - To report a vulnerability, please email security@cloudera.com . For more information, visit https://www.cloudera.com/contact-us/security.html .
 - To report a bug, please do it in "GitHub Issues".

## Supplemental Disclaimer
Please read the following before proceeding.

Cloudera, Inc. (“Cloudera”) makes the cmlutil available as an open source tool for the convenience of its users.  Although Cloudera expects that the tool will help users working with Cloudera Machine Learning, Cloudera makes cmlutil available “as is” and without any warranty or support.  By downloading and using cmlutil, you acknowledge the foregoing statement and agree that Cloudera is not responsible or liable in any way for your use of cmlutil.