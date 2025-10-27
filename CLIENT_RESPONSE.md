# Response to Client SSL/V1 API Issue

## Issue Summary

Your import is failing because of an **SSL certificate verification error**. This happens when using CMLUtils with enterprise CML deployments that have custom SSL certificates (like Bank of America's deployment at `gis.apps.pvcbeta.bankofamerica.com`).

## The Error You're Seeing

```
SSLError: certificate verify failed: unable to get local issuer certificate
```

This occurs because:
1. Your CML instance uses an enterprise/custom SSL certificate
2. Python's `requests` library doesn't trust this certificate by default
3. The tool needs to be configured to use your enterprise CA certificate

## Solution 1: Configure CA Certificate (REQUIRED for Enterprise CML)

You need to tell CMLUtils where to find your enterprise CA certificate.

### Steps:

**1. Obtain your CA certificate**

Choose one of these methods:

**Option A - From IT/Security Team (RECOMMENDED)**
- Contact your IT/Security team
- Request "Bank of America Enterprise Root CA Certificate Bundle"
- They should provide a `.crt` or `.pem` file

**Option B - Export from Browser**
- Open https://gis.apps.pvcbeta.bankofamerica.com in Chrome/Firefox
- Click the padlock icon in address bar
- Click "Certificate" → "Details" → "Export"
- Save as PEM format (`.crt` or `.pem`)

**Option C - Use System Certificate Store**
- Linux: `/etc/ssl/certs/ca-bundle.crt`
- RHEL/CentOS: `/etc/pki/tls/certs/ca-bundle.crt`
- If these don't work, your system admin can provide the correct path

**2. Update your import config**

Edit: `~/.cmlutils/import-config.ini`

Add or update the config with **both API keys** and the `ca_path`:

```ini
[cdv]
url=https://gis.apps.pvcbeta.bankofamerica.com
username=nbe226r
apiv1_key=<your_v1_api_key>
apiv2_key=<your_v2_api_key>
source_dir=/path/to/your/cmlutils-exports
output_dir=/path/to/your/import-logs
ca_path=/path/to/your/enterprise-ca-bundle.crt
```

**Important Notes**:
- **You need BOTH API keys** (`apiv1_key` and `apiv2_key`) because CML has separate keys for V1 and V2 APIs
- Get V1 key from CML: Profile → API Keys → Legacy API Key (V1)
- Get V2 key from CML: Profile → API Keys → API Key (V2)
- Replace `/path/to/your/enterprise-ca-bundle.crt` with the actual path to your certificate

**3. Update your export config too**

If you're also exporting, update: `~/.cmlutils/export-config.ini`

```ini
[cdv]
url=https://gis.apps.pvcbeta.bankofamerica.com
username=nbe226r
apiv1_key=<your_v1_api_key>
apiv2_key=<your_v2_api_key>
output_dir=/path/to/your/cmlutils-exports
ca_path=/path/to/your/enterprise-ca-bundle.crt
```

**4. Try the import again**

```bash
cmlutil project import --project_name cdv --verbose
```

## Solution 2: Code Update (Already Fixed)

I've **already pushed a code fix** that removes the unnecessary V1 API user validation. This makes the tool:
- ✅ More compatible with enterprise CML deployments
- ✅ Eliminates the V1 API dependency you were seeing
- ✅ Still validates properly using V2 API

**To get the fix**:

```bash
cd /path/to/cmlutils
git pull origin main
pip install -e .
```

## Why Was It Using V1 API?

The tool was originally designed to only use V1 API keys and generate V2 keys from them. This doesn't work with modern CML deployments where:
- **V1 and V2 API keys are separate and different**
- You can't use a V2 key to call V1 endpoints
- You can't generate one from the other

The validator was also checking if the username exists using the V1 endpoint `/api/v1/users/$username`, causing SSL errors with enterprise certificates.

**This is now fixed** in the latest version:
- ✅ Supports both V1 and V2 API keys independently
- ✅ Uses the right key for the right API version
- ✅ Removed redundant V1 user validation
- ✅ Gracefully handles missing V1 key (some checks will be skipped)

## Summary of What You Need to Do

1. ✅ **Pull latest code**: `git pull origin main` (includes V1/V2 API fix)
2. ✅ **Get BOTH API keys from CML**:
   - V1 API Key: Profile → API Keys → Legacy API Key
   - V2 API Key: Profile → API Keys → API Key
3. ✅ **Get your CA certificate** from IT/Security team
4. ✅ **Update config files** with `apiv1_key`, `apiv2_key`, and `ca_path`
5. ✅ **Try import again**

## Testing Without CA Certificate (Not Recommended)

If you're just testing and can't get the CA certificate immediately, you can temporarily disable SSL verification. **DO NOT use this in production**:

Edit `cmlutils/utils.py` and find the `call_api_v1` and `call_api_v2` functions. Add `verify=False` to the requests calls:

```python
# In call_api_v1
resp = s.request(
    method=method,
    url=complete_url,
    headers=headers,
    json=json_data,
    verify=False  # ADD THIS LINE (TEMPORARY ONLY)
)

# In call_api_v2
response = s.request(
    method=method,
    url=complete_url,
    headers=headers,
    json=json_data,
    verify=False  # ADD THIS LINE (TEMPORARY ONLY)
)
```

Again, **this is not secure** and should only be used for initial testing.

## Need More Help?

If you're still having issues after:
1. Pulling the latest code
2. Adding the `ca_path` to your config

Please send:
- Your config file (with API keys redacted)
- The full error message
- Confirmation that the ca_path file exists: `ls -la /path/to/your/cert.crt`

