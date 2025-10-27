# API Key Architecture Issue and Fix Plan

## Current Problem

The client's error reveals a fundamental architecture issue with how CMLUtils handles API keys.

### How It Currently Works (BROKEN)

1. **Config reading** (`project_entrypoint.py` lines 85-94):
   ```python
   # Try apiv2_key first, fallback to apiv1_key
   try:
       api_key = config.get(project_name, API_V2_KEY)  # Gets V2 key
   except NoOptionError:
       api_key = config.get(project_name, API_V1_KEY)  # Gets V1 key
   output_config[API_V1_KEY] = api_key  # Stores EITHER key as "V1 key"
   ```

2. **Base class** (`base.py` lines 28-48):
   ```python
   @property
   def apiv2_key(self) -> str:
       # Calls V1 API endpoint /api/v1/users/$username/apikey
       # to GENERATE a V2 key from the V1 key
       response = call_api_v1(
           host=self.host,
           endpoint=endpoint,
           api_key=self.api_key,  # Uses what was stored as "V1 key"
           ...
       )
       return response.json()["apiKey"]
   ```

3. **V1 API calls** (`projects.py` line 190-196):
   ```python
   def get_cdsw_runtimes(host: str, api_key: str, ca_path: str):
       endpoint = "api/v1/runtimes"  # V1 endpoint - requires V1 key!
       response = call_api_v1(...)
   ```

### Why This Breaks

**Scenario: Client only has V2 API key**

1. Config has `apiv2_key=abc123...`
2. System reads V2 key and stores it as `api_key` (thinking it's V1)
3. Code calls `self.apiv2_key` property
4. Property tries to call `/api/v1/users/$username/apikey` **with V2 key**
5. **FAILS**: Can't call V1 endpoint with V2 key
6. Additional issue: Can't call `/api/v1/runtimes` without V1 key

**Root Cause**: The system assumes it always has a V1 key and can generate V2 keys from it. This is wrong for modern CML deployments where V1 and V2 keys are separate.

---

## Solution

We need to support **BOTH** API keys independently.

### Changes Required

#### 1. Update Config Reading (`project_entrypoint.py`)

```python
def read_config(config_file_path: str, project_name: str):
    # ... existing code ...
    
    # Read BOTH keys independently
    try:
        apiv1_key = config.get(project_name, API_V1_KEY)
    except NoOptionError:
        apiv1_key = None
    
    try:
        apiv2_key = config.get(project_name, API_V2_KEY)
    except NoOptionError:
        apiv2_key = None
    
    # Validate at least one key exists
    if not apiv1_key and not apiv2_key:
        print(f"ERROR: Must provide either {API_V1_KEY} or {API_V2_KEY} in config")
        raise
    
    # Store both
    output_config[API_V1_KEY] = apiv1_key
    output_config[API_V2_KEY] = apiv2_key
    
    return output_config
```

#### 2. Update Base Class (`base.py`)

```python
class BaseWorkspaceInteractor(object):
    def __init__(
        self,
        host: str,
        username: str,
        project_name: str,
        api_key: str,  # V1 key (optional)
        ca_path: str,
        project_slug: str,
        apiv2_key: str = None,  # V2 key (optional)
    ) -> None:
        self.host = host
        self.username = username
        self.project_name = project_name
        self.api_key = api_key  # V1 key
        self.ca_path = ca_path
        self.project_slug = project_slug
        self._apiv2_key = apiv2_key  # Store V2 key directly
    
    @property
    def apiv2_key(self) -> str:
        # If we already have V2 key, use it
        if self._apiv2_key:
            return self._apiv2_key
        
        # If we only have V1 key, generate V2 key (legacy behavior)
        if self.api_key:
            endpoint = Template(ApiV1Endpoints.API_KEY.value).substitute(
                username=self.username
            )
            json_data = {
                "expiryDate": (datetime.now() + timedelta(weeks=1)).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                )
            }
            response = call_api_v1(
                host=self.host,
                endpoint=endpoint,
                method="POST",
                api_key=self.api_key,
                json_data=json_data,
                ca_path=self.ca_path,
            )
            return response.json()["apiKey"]
        
        raise ValueError("No V2 API key available and cannot generate from V1 key")
```

#### 3. Update All Instantiations

Everywhere we create `ProjectExporter` or `ProjectImporter`:

```python
# Old
exporter = ProjectExporter(
    host=url,
    username=username,
    project_name=project_name,
    api_key=apiv1_key,
    top_level_dir=output_dir,
    ca_path=ca_path,
    project_slug=project_slug,
    owner_type=owner_type,
)

# New
exporter = ProjectExporter(
    host=url,
    username=username,
    project_name=project_name,
    api_key=config.get(API_V1_KEY),  # May be None
    top_level_dir=output_dir,
    ca_path=ca_path,
    project_slug=project_slug,
    owner_type=owner_type,
    apiv2_key=config.get(API_V2_KEY),  # May be None
)
```

#### 4. Handle V1 API Calls Gracefully

For functions that still need V1 API (like `get_cdsw_runtimes`):

```python
def get_cdsw_runtimes(host: str, api_key: str, ca_path: str) -> list[dict[str, Any]]:
    if not api_key:
        # Try V2 API endpoint for runtimes
        return get_cdsw_runtimes_v2(host, api_key, ca_path)
    
    # Use V1 API if V1 key available
    endpoint = "api/v1/runtimes"
    response = call_api_v1(
        host=host, endpoint=endpoint, method="GET", api_key=api_key, ca_path=ca_path
    )
    response_dict = response.json()
    return response_dict["runtimes"]

def get_cdsw_runtimes_v2(host: str, apiv2_key: str, ca_path: str) -> list[dict[str, Any]]:
    # Use V2 API endpoint /api/v2/runtimes
    # (Already implemented in ProjectExporter.get_available_runtimes_v2)
    ...
```

---

## Migration Strategy

### Phase 1: Support Both Keys (Backwards Compatible)

1. Update base class to accept both keys
2. Update config reader to read both keys
3. Update all instantiations to pass both keys
4. Keep legacy behavior: if only V1 key, generate V2

### Phase 2: Migrate V1 API Calls to V2

1. Replace `/api/v1/runtimes` with `/api/v2/runtimes`
2. Remove dependency on V1 key for runtimes
3. Remove validator dependency on V1 key

### Phase 3: Make V2 Key Primary

1. Update documentation to recommend V2 keys
2. Make V1 key optional
3. Keep V1 support for legacy deployments

---

## Immediate Fix for Client

**Option 1: Add V1 Key to Config (QUICK FIX)**

Tell client to add their V1 API key to config:

```ini
[cdv]
url=https://gis.apps.pvcbeta.bankofamerica.com
username=nbe226r
apiv1_key=<their_v1_key>
apiv2_key=<their_v2_key>
ca_path=/path/to/ca-bundle.crt
```

**Option 2: Implement Full Fix (PROPER SOLUTION)**

Implement the changes above to support both keys independently.

---

## Files That Need Changes

1. `cmlutils/base.py` - Add apiv2_key parameter
2. `cmlutils/project_entrypoint.py` - Read both keys from config
3. `cmlutils/projects.py` - Pass both keys to constructors
4. `cmlutils/validator.py` - Handle missing V1 key gracefully
5. Config files (`export-config.ini`, `import-config.ini`) - Document both keys

---

## Testing Plan

1. **Config with only V1 key**: Should work (legacy behavior)
2. **Config with only V2 key**: Should work (new behavior)
3. **Config with both keys**: Should use each appropriately
4. **Enterprise CML with custom SSL**: Should work with ca_path configured

