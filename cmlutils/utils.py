import json
import logging
import os
import csv
import shutil
import urllib
from encodings import utf_8
from string import Template

import requests
from flatten_json import flatten
from requests.adapters import HTTPAdapter, Retry


def call_api_v1(
    host: str,
    endpoint: str,
    method: str,
    api_key: str,
    json_data: dict = None,
    ca_path: str = "",
) -> requests.Response:
    import time
    
    url = urllib.parse.urljoin(host, endpoint)
    
    # Check if verbose mode is enabled
    verbose = os.environ.get('CMLUTILS_VERBOSE', 'False').lower() == 'true'
    
    if verbose:
        logging.debug("API v1 Request: %s %s", method.upper(), url)
        if json_data:
            logging.debug("API v1 Request Body: %s", json.dumps(json_data, indent=2))
    
    s = requests.Session()
    retries = Retry(
        total=3,
        backoff_factor=0.1,
        status_forcelist=[500, 502, 503, 504],
    )
    s.mount("http://", HTTPAdapter(max_retries=retries))
    s.mount("https://", HTTPAdapter(max_retries=retries))
    headers = {"Content-Type": "application/json"}
    resp = None
    
    start_time = time.time()
    try:
        if json_data != None:
            resp = s.request(
                method=method.upper(),
                url=url,
                auth=(api_key, ""),
                headers=headers,
                json=json_data,
                verify=False if ca_path.lower() == "false" else (ca_path if ca_path != "" else True),
            )
        else:
            resp = s.request(
                method=method.upper(),
                url=url,
                auth=(api_key, ""),
                headers=headers,
                verify=False if ca_path.lower() == "false" else (ca_path if ca_path != "" else True),
            )
        
        elapsed_time = time.time() - start_time
        
        if verbose:
            logging.debug("API v1 Response: %s (Status: %d, Time: %.2fs)", 
                         url, resp.status_code, elapsed_time)
            if resp.headers.get("content-type", "").startswith("application/json"):
                try:
                    response_data = resp.json()
                    # Log only first few lines of response to avoid overwhelming logs
                    response_str = json.dumps(response_data, indent=2)
                    if len(response_str) > 1000:
                        response_str = response_str[:1000] + "... (truncated)"
                    logging.debug("API v1 Response Body: %s", response_str)
                except:
                    logging.debug("API v1 Response Body: (non-JSON or too large)")
        
        resp.raise_for_status()  # Raise an exception for 4xx or 5xx errors
        return resp
    except requests.exceptions.RequestException as e:
        elapsed_time = time.time() - start_time
        if verbose:
            logging.debug("API v1 Request Failed: %s (Time: %.2fs, Error: %s)", 
                         url, elapsed_time, str(e))
        if resp != None and "application/json" in resp.headers.get("content-type", ""):
            logging.error("Error response from API: %s", resp.json())
        raise


def call_api_v2(
    host: str,
    endpoint: str,
    method: str,
    user_token: str,
    json_data: dict = None,
    ca_path: str = "",
) -> requests.Response:
    import time
    
    url = urllib.parse.urljoin(host, endpoint)
    
    # Check if verbose mode is enabled
    verbose = os.environ.get('CMLUTILS_VERBOSE', 'False').lower() == 'true'
    
    if verbose:
        logging.debug("API v2 Request: %s %s", method.upper(), url)
        if json_data:
            logging.debug("API v2 Request Body: %s", json.dumps(json_data, indent=2))
    
    s = requests.Session()
    retries = Retry(
        total=3,
        backoff_factor=0.1,
        status_forcelist=[500, 502, 503, 504],
    )
    s.mount("http://", HTTPAdapter(max_retries=retries))
    s.mount("https://", HTTPAdapter(max_retries=retries))
    headers = {
        "Content-Type": "application/json",
        "Authorization": "Bearer {}".format(user_token),
    }
    resp = None
    
    start_time = time.time()
    try:
        if json_data != None:
            resp = s.request(
                method=method.upper(),
                url=url,
                headers=headers,
                json=json_data,
                verify=False if ca_path.lower() == "false" else (ca_path if ca_path != "" else True),
            )
        else:
            resp = s.request(
                method=method.upper(),
                url=url,
                headers=headers,
                verify=False if ca_path.lower() == "false" else (ca_path if ca_path != "" else True),
            )
        
        elapsed_time = time.time() - start_time
        
        if verbose:
            logging.debug("API v2 Response: %s (Status: %d, Time: %.2fs)", 
                         url, resp.status_code, elapsed_time)
            if resp.headers.get("content-type", "").startswith("application/json"):
                try:
                    response_data = resp.json()
                    # Log only first few lines of response to avoid overwhelming logs
                    response_str = json.dumps(response_data, indent=2)
                    if len(response_str) > 1000:
                        response_str = response_str[:1000] + "... (truncated)"
                    logging.debug("API v2 Response Body: %s", response_str)
                except:
                    logging.debug("API v2 Response Body: (non-JSON or too large)")
        
        resp.raise_for_status()  # Raise an exception for 4xx or 5xx errors
        return resp
    except requests.exceptions.RequestException as e:
        elapsed_time = time.time() - start_time
        if verbose:
            logging.debug("API v2 Request Failed: %s (Time: %.2fs, Error: %s)", 
                         url, elapsed_time, str(e))
        logging.warning(f"Error: {e}")
        if resp != None and "application/json" in resp.headers.get("content-type", ""):
            logging.error("Error response from API: %s", resp.json())
        raise


def download_file(url: str, filepath: str, ca_path: str = ""):
    with requests.get(url, stream=True, verify=False if ca_path.lower() == "false" else (ca_path if ca_path != "" else True)) as r:
        with open(filepath, "wb") as f:
            shutil.copyfileobj(r.raw, f)


def extract_fields(json_data, field_map):
    output = {}
    for old_field, new_field in field_map.items():
        try:
            value = json_data[old_field]
        except KeyError:
            continue
        output[new_field] = value
    return output


def read_json_file(file_path):
    with open(file_path, "r", encoding=utf_8.getregentry().name) as f:
        json_data = json.load(f)
    return json_data


def write_json_file(file_path, json_data):
    with open(file_path, "w", encoding=utf_8.getregentry().name) as f:
        json.dump(json_data, f)
    # Set file permissions to 600 (read and write only for the owner)
    os.chmod(file_path, 0o600)


def flatten_json_data(json_data):
    return flatten(json_data, ".")


def get_best_runtime(json_list, edition, editor, kernel, short_version, full_version):
    # Best match with all five criteria matching
    for json_obj in json_list:
        if (
            "kernel" in json_obj
            and "edition" in json_obj
            and "editor" in json_obj
            and "shortVersion" in json_obj
            and "fullVersion" in json_obj
        ):
            if (
                json_obj["kernel"] == kernel
                and json_obj["edition"] == edition
                and json_obj["editor"] == editor
                and json_obj["shortVersion"] == short_version
                and json_obj["fullVersion"] == full_version
            ):
                if "imageIdentifier" in json_obj:
                    return json_obj["imageIdentifier"]

    # Best match with four criteria matching
    for json_obj in json_list:
        if (
            "kernel" in json_obj
            and "edition" in json_obj
            and "editor" in json_obj
            and "shortVersion" in json_obj
        ):
            if (
                json_obj["kernel"] == kernel
                and json_obj["edition"] == edition
                and json_obj["editor"] == editor
                and json_obj["shortVersion"] == short_version
            ):
                if "imageIdentifier" in json_obj:
                    return json_obj["imageIdentifier"]

    # If not Atleast three criterias are matching
    for json_obj in json_list:
        if "kernel" in json_obj and "edition" in json_obj and "editor" in json_obj:
            if (
                json_obj["kernel"] == kernel
                and json_obj["edition"] == edition
                and json_obj["editor"] == editor
            ):
                if "imageIdentifier" in json_obj:
                    return json_obj["imageIdentifier"]

    # If not atleast two criteria kernel and editor are matching
    for json_obj in json_list:
        if "kernel" in json_obj and "edition" in json_obj:
            if json_obj["kernel"] == kernel and json_obj["editor"] == editor:
                if "imageIdentifier" in json_obj:
                    return json_obj["imageIdentifier"]

    # If not atleast kernel is matching
    for json_obj in json_list:
        if "kernel" in json_obj:
            if json_obj["kernel"] == kernel:
                if "imageIdentifier" in json_obj:
                    return json_obj["imageIdentifier"]

    return None


def find_runtime(runtime_list, runtime_id: int):
    for runtime in runtime_list:
        if "id" in runtime and runtime["id"] == runtime_id:
            return {
                "runtime_kernel": runtime["kernel"],
                "runtime_edition": runtime["edition"],
                "runtime_editor": runtime["editor"],
                "runtime_fullversion": runtime["fullVersion"],
                "runtime_shortversion": runtime["shortVersion"],
            }
    return None


def get_absolute_path(path: str) -> str:
    # Special case: if path is "False" (for disabling SSL verification), return it as-is
    if path.lower() == "false":
        return path
    if path.startswith("~"):
        return path.replace("~", os.path.expanduser("~"), 1)
    return os.path.abspath(path=path)


def parse_runtimes_v2(runtimes):
    legacy_runtime_image_map = _get_runtimes_v2(
        runtimes, editor="Workbench", edition="Standard"
    )
    return legacy_runtime_image_map


def _get_runtimes_v2(runtimes, editor="Workbench", edition="Standard"):
    legacy_runtime_image_map = {}
    legacy_runtime_kernel_map = {}

    logging.info(
        "Populating Engine to Runtimes Mapping for editor: %s, edition: %s",
        editor,
        edition,
    )

    for image_details in runtimes:
        if image_details["editor"] == editor and image_details["edition"] == edition:
            if "Python" in image_details["kernel"]:
                if "python3" not in legacy_runtime_image_map:
                    legacy_runtime_kernel_map["python3"] = image_details["kernel"]
                    legacy_runtime_image_map["python3"] = image_details[
                        "image_identifier"
                    ]
                    legacy_runtime_image_map["python2"] = image_details[
                        "image_identifier"
                    ]
                else:
                    if image_details["kernel"] > legacy_runtime_kernel_map["python3"]:
                        legacy_runtime_kernel_map["python3"] = image_details["kernel"]
                        legacy_runtime_image_map["python3"] = image_details[
                            "image_identifier"
                        ]
                        legacy_runtime_image_map["python2"] = image_details[
                            "image_identifier"
                        ]

            if "R" in image_details["kernel"]:
                if "r" not in legacy_runtime_image_map:
                    legacy_runtime_kernel_map["r"] = image_details["kernel"]
                    legacy_runtime_image_map["r"] = image_details["image_identifier"]
                else:
                    if image_details["kernel"] > legacy_runtime_kernel_map["r"]:
                        legacy_runtime_kernel_map["r"] = image_details["kernel"]
                        legacy_runtime_image_map["r"] = image_details[
                            "image_identifier"
                        ]

            if "Scala" in image_details["kernel"]:
                if "scala" not in legacy_runtime_image_map:
                    legacy_runtime_kernel_map["scala"] = image_details["kernel"]
                    legacy_runtime_image_map["scala"] = image_details[
                        "image_identifier"
                    ]
                else:
                    if image_details["kernel"] > legacy_runtime_kernel_map["scala"]:
                        legacy_runtime_kernel_map["scala"] = image_details["kernel"]
                        legacy_runtime_image_map["scala"] = image_details[
                            "image_identifier"
                        ]

    # Assigning Default runtime to Python3
    legacy_runtime_image_map["default"] = legacy_runtime_image_map["python3"]

    return legacy_runtime_image_map


def compare_metadata(
    import_data, export_data, import_data_list, export_data_list, skip_field=None
):
    if skip_field is None:
        skip_field = []

    data_list_diff = list(set(sorted(export_data_list)) - set(sorted(import_data_list)))
    config_differences = {}

    import_data_dict = {data["name"]: data for data in import_data}
    export_data_dict = {data["name"]: data for data in export_data}

    for name, im_data in import_data_dict.items():
        ex_data = export_data_dict.get(name)

        if ex_data is None:
            continue

        for key, value in im_data.items():
            if key not in skip_field:
                ex_value = ex_data.get(key)
                if ex_value is not None and str(ex_value) != str(value):
                    difference = ["{} value in destination is {}, and source is {}".format(
                        key, str(value), str(ex_value))]
                    if config_differences.get(name):
                        config_differences[name].extend(difference)
                    else:
                        config_differences[name]= difference
    return data_list_diff, config_differences


def update_verification_status(data_diff, message):
    if data_diff:
        logging.info("\033[31mERROR: {} Not Successful\033[0m".format(message))
    else:
        logging.info("\033[32mSUCCESS: {} Successful \033[0m".format(message))
