# Client SSL Certificate Issue Resolution

## Problem Summary

The client is experiencing two issues when importing to their enterprise CML deployment:

### Issue 1: SSL Certificate Verification Failure
```
SSLError: certificate verify failed: unable to get local issuer certificate
```

**Root Cause**: The client's CML instance (`gis.apps.pvcbeta.bankofamerica.com`) uses an enterprise/self-signed SSL certificate that Python doesn't trust by default.

### Issue 2: Validator Uses V1 API
```
API v1 Request: GET https://gis.apps.pvcbeta.bankofamerica.com/api/v1/users/nbe226r
```

**Root Cause**: The `validator.py` still uses V1 API endpoint `/api/v1/users/$username` for user validation during import.

---

## Solutions

### Solution 1: Configure CA Certificate Path (RECOMMENDED)

The client needs to add the `ca_path` parameter to their import config file:

**File**: `~/.cmlutils/import-config.ini`

```ini
[cdv]
url=https://gis.apps.pvcbeta.bankofamerica.com
username=nbe226r
apiv2_key=<their_api_key>
source_dir=/path/to/exports
output_dir=/path/to/logs
ca_path=/path/to/enterprise-ca-bundle.crt
```

**Where to get the certificate**:
1. **From IT/Security team**: Request the enterprise CA certificate bundle
2. **Export from browser**: 
   - Open https://gis.apps.pvcbeta.bankofamerica.com in Chrome/Firefox
   - View certificate → Export as PEM format
3. **System certificate store**: `/etc/ssl/certs/ca-bundle.crt` (Linux) or `/etc/pki/tls/certs/ca-bundle.crt` (RHEL)

### Solution 2: Disable SSL Verification (NOT RECOMMENDED for Production)

If this is just for testing, we can add a config option to disable SSL verification.

**Would require code change to add**:
```ini
[cdv]
verify_ssl=False
```

---

## Code Changes Needed

### Option A: Remove User Validation (RECOMMENDED)

The user validation in `validator.py` is redundant because:
- V2 API will return proper errors if user doesn't exist
- Import will fail gracefully with clear error messages
- Removes dependency on V1 API

**Files to modify**:
- `cmlutils/validator.py`: Comment out or remove `UserNameImportValidator` from `initialize_import_validators()`

### Option B: Make User Validation Optional

Add a config flag to skip validation:
```ini
[cdv]
skip_user_validation=True
```

### Option C: Migrate User Validation to V2 API

There's no direct V2 equivalent for `/api/v1/users/$username`, but we can validate the user by:
- Trying to call any V2 endpoint (like list projects)
- If API key is invalid, it will fail with 401
- If valid, proceed with import

---

## Immediate Client Instructions

**Send this to the client**:

```
Hi,

The SSL error occurs because your CML instance uses an enterprise certificate. 
To fix this, please add the following line to your import config file:

File: ~/.cmlutils/import-config.ini

[cdv]
url=https://gis.apps.pvcbeta.bankofamerica.com
username=nbe226r
apiv2_key=<your_api_key>
source_dir=/path/to/your/exports
output_dir=/path/to/your/logs
ca_path=/path/to/your/ca-certificate.crt

To get the CA certificate:
1. Contact your IT/Security team for the "Bank of America Enterprise CA Bundle"
2. Or export it from your browser when visiting the CML URL
3. Save it to a file and point ca_path to that file

If ca_path=False or is not set, Python will try to verify the SSL certificate 
using system defaults, which don't include your enterprise certificate.

Alternatively, if you don't have the certificate and this is just for testing,
you can temporarily disable SSL verification by editing cmlutils/utils.py and
adding verify=False to the requests calls (not recommended for production).
```

---

## Recommended Fix (Code)

Remove the V1 user validation from import validators since it's redundant.

