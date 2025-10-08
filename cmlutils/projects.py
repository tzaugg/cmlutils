import json
import logging
import os
import signal
import subprocess
import urllib.parse
from datetime import datetime, timedelta
from encodings import utf_8
from string import Template
from sys import stdout
from typing import Any

from requests import HTTPError  # pyright: ignore[reportMissingModuleSource]

from cmlutils import constants, legacy_engine_runtime_constants
from cmlutils.base import BaseWorkspaceInteractor
from cmlutils.cdswctl import cdswctl_login, obtain_cdswctl
from cmlutils.constants import ApiV1Endpoints, ApiV2Endpoints
from cmlutils.directory_utils import (
    ensure_project_data_and_metadata_directory_exists,
    get_applications_metadata_file_path,
    get_jobs_metadata_file_path,
    get_models_metadata_file_path,
    get_project_data_dir_path,
    get_project_metadata_file_path,
)
from cmlutils.ssh import open_ssh_endpoint
from cmlutils.utils import (
    call_api_v1,
    call_api_v2,
    extract_fields,
    find_runtime,
    flatten_json_data,
    get_best_runtime,
    read_json_file,
    write_json_file,
)



def is_project_configured_with_runtimes(
    host: str,
    username: str,
    project_name: str,
    api_key: str,
    ca_path: str,
    project_slug: str,
) -> bool:
    # Use V2 API - first get V2 token
    endpoint_api_key = Template(ApiV1Endpoints.API_KEY.value).substitute(
        username=username
    )
    json_data = {
        "expiryDate": (datetime.now() + timedelta(weeks=1)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
    }
    response_key = call_api_v1(
        host=host,
        endpoint=endpoint_api_key,
        method="POST",
        api_key=api_key,
        json_data=json_data,
        ca_path=ca_path,
    )
    apiv2_key = response_key.json()["apiKey"]
    
    # Search for the project using V2 API
    search_option = {"name": project_name}
    encoded_option = urllib.parse.quote(json.dumps(search_option).replace('"', '"'))
    endpoint = Template(ApiV2Endpoints.SEARCH_PROJECT.value).substitute(
        search_option=encoded_option
    )
    response = call_api_v2(
        host=host, endpoint=endpoint, method="GET", user_token=apiv2_key, ca_path=ca_path
    )
    project_list = response.json()["projects"]
    if project_list:
        for project in project_list:
            if project["name"] == project_name:
                # V2 API uses "default_engine_type" not "default_project_engine_type"
                engine_type = str(project.get("default_engine_type", "")).lower()
                logging.info(f"Project {project_name} engine type: {engine_type}")
                return engine_type == "ml_runtime"
    return False


def get_ignore_files(
    host: str,
    username: str,
    project_name: str,
    api_key: str,
    ca_path: str,
    ssh_port: str,
    project_slug: str,
    top_level_dir: str,
) -> str:
    endpoint = Template(ApiV1Endpoints.PROJECT_FILE.value).substitute(
        username=username, project_name=project_slug, filename=constants.FILE_NAME
    )
    try:
        logging.info(
            "The files included in %s will not be migrated for the project %s",
            constants.FILE_NAME,
            project_name,
        )
        response = call_api_v1(
            host=host, endpoint=endpoint, method="GET", api_key=api_key, ca_path=ca_path
        )
        a = response.text + "\n" + constants.FILE_NAME
        with open(
            os.path.join(top_level_dir, project_name, constants.IGNORE_FILE_PATH),
            "w",
            encoding=utf_8.getregentry().name,
        ) as f:
            f.writelines(a.strip())
        # Set file permissions to 600 (read and write only for the owner)
        os.chmod(
            os.path.join(top_level_dir, project_name, constants.IGNORE_FILE_PATH), 0o600
        )
        return os.path.join(top_level_dir, project_name, constants.IGNORE_FILE_PATH)
    except HTTPError as e:
        if e.response.status_code == 404:
            logging.warning(
                "Export ignore file does not exist. Hence, all files of the project %s will be migrated except .cache and .local.",
                project_name,
            )
            logging.info(
                "Since the %s file was not provided, a default file has been generated to exclude the directories .cache and .local from migration.",
                constants.FILE_NAME,
            )
            entries_content = "\n".join(constants.DEFAULT_ENTRIES)
            create_command = [
                "ssh",
                "-p",
                str(ssh_port),
                "-oStrictHostKeyChecking=no",
                constants.CDSW_ROOT_USER,
                f"echo -e '{entries_content}' > {constants.FILE_NAME}",
            ]
            subprocess.run(create_command)
            entries_content = entries_content + "\n" + constants.FILE_NAME
            with open(
                os.path.join(top_level_dir, project_name, constants.IGNORE_FILE_PATH),
                "w",
                encoding=utf_8.getregentry().name,
            ) as f:
                f.writelines(entries_content.strip())
            # Set file permissions to 600 (read and write only for the owner)
            os.chmod(
                os.path.join(top_level_dir, project_name, constants.IGNORE_FILE_PATH),
                0o600,
            )
            return os.path.join(top_level_dir, project_name, constants.IGNORE_FILE_PATH)
        else:
            logging.error("Failed to find ignore files due to network issues.")
            raise e


def get_rsync_enabled_runtime_id(host: str, api_key: str, ca_path: str) -> int:
    logging.info("Looking for rsync-enabled runtime...")
    runtime_list = get_cdsw_runtimes(host=host, api_key=api_key, ca_path=ca_path)
    logging.info(f"Found {len(runtime_list)} runtimes")
    
    for runtime in runtime_list:
        if "rsync" in runtime["edition"].lower():
            logging.info("Rsync enabled runtime is available.")
            return runtime["id"]
    logging.info("Rsync enabled runtime is not available, looking for fallback...")
    
    # Fallback: if no rsync runtime, use the first available Python runtime
    for runtime in runtime_list:
        edition = runtime.get("edition", "").lower()
        status = runtime.get("status", "")
        logging.debug(f"Checking runtime: edition={edition}, status={status}")
        if "python" in edition and status == "AVAILABLE":
            logging.info(f"Using fallback Python runtime: {runtime.get('description', runtime.get('edition'))}")
            return runtime["id"]
    
    # If still none, just return the first available runtime
    if runtime_list and len(runtime_list) > 0:
        runtime = runtime_list[0]
        logging.info(f"Using first available runtime: {runtime.get('description', runtime.get('edition'))} (id={runtime.get('id')})")
        return runtime["id"]
    
    logging.error("No runtimes available at all!")
    return -1


def get_cdsw_runtimes(host: str, api_key: str, ca_path: str) -> list[dict[str, Any]]:
    endpoint = "api/v1/runtimes"
    response = call_api_v1(
        host=host, endpoint=endpoint, method="GET", api_key=api_key, ca_path=ca_path
    )
    response_dict = response.json()
    return response_dict["runtimes"]


def transfer_project_files(
    sshport: int,
    source: str,
    destination: str,
    retry_limit: int,
    project_name: str,
    log_filedir: str,
    exclude_file_path: str = None,
):
    log_filename = log_filedir + constants.LOG_FILE
    verbose = os.environ.get('CMLUTILS_VERBOSE', 'False').lower() == 'true'
    
    logging.info("Transfering files over ssh from sshport %s", sshport)
    if verbose:
        logging.debug("Transfer details - Source: %s, Destination: %s, SSH Port: %s", 
                     source, destination, sshport)
        logging.debug("Using exclude file: %s", exclude_file_path if exclude_file_path else "None")
        logging.debug("Retry limit set to: %d", retry_limit)
    
    ssh_directive = f"ssh -p {sshport} -oStrictHostKeyChecking=no"
    subprocess_arguments = [
        "rsync",
        "--delete",
        "-P",
        "-r",
        "-v",
        "-i",
        "-a",
        "-e",
        ssh_directive,
        "--log-file",
        log_filename,
    ]
    if exclude_file_path is not None:
        logging.info("Exclude file path is provided for file transfer")
        subprocess_arguments.append(f"--exclude-from={exclude_file_path}")
    subprocess_arguments.extend([source, destination])
    for i in range(retry_limit):
        if verbose:
            logging.debug("Rsync attempt %d of %d", i + 1, retry_limit)
            logging.debug("Executing rsync command: %s", " ".join(subprocess_arguments))
        
        return_code = subprocess.call(subprocess_arguments)
        if return_code == 0:
            logging.info("Project files transfered successfully")
            return
        
        if verbose:
            logging.debug("Rsync attempt %d failed with return code %d", i + 1, return_code)
        
        logging.warning("Got non zero return code. Retrying...")
        
    if return_code != 0:
        logging.error(
            "Retries exhausted for rsync.. Failing script for project %s", project_name
        )
        raise RuntimeError("Retries exhausted for rsync.. Failing script")


def verify_files(
    sshport: int,
    source: str,
    destination: str,
    retry_limit: int,
    project_name: str,
    log_filedir: str,
    exclude_file_path: str = None,
):
    log_filename = log_filedir + constants.LOG_FILE
    logging.info("Validating files over ssh from sshport %s", sshport)
    ssh_directive = f"ssh -p {sshport} -oStrictHostKeyChecking=no"
    subprocess_arguments = [
        "rsync",
        "-n",
        "-r",
        "-c",
        "-a",
        "--delete",
        "--itemize-changes",
        "--out-format=%n",
        "-e",
        ssh_directive,
        "--log-file",
        log_filename,
    ]
    if exclude_file_path is not None:
        logging.info("Exclude file path is provided for file Verification")
        subprocess_arguments.append(f"--exclude-from={exclude_file_path}")
    subprocess_arguments.extend([source, destination])
    for i in range(retry_limit):
        result = subprocess.run(
            subprocess_arguments, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        if result.returncode == 0:
            # Removing any . files
            file_list = (
                result.stdout.decode("utf-8")
                .strip()
                .replace(" ", "")
                .replace("./", "")
                .replace("deleting", "")
                .replace("\t", "")
                .split("\n")
            )
            # Use list comprehension to remove empty strings and .local and ,cache files
            filtered_list = [
                file
                for file in file_list
                if (file != "" and
                    not file.startswith('.'))
                 ]
            return filtered_list
        logging.warning("Got non zero return code. Retrying...")
    if result.returncode != 0:
        logging.error(
            "Retries exhausted for rsync.. Failing script for project %s", project_name
        )
        raise RuntimeError("Retries exhausted for rsync.. Failing script")


def test_file_size(sshport: int, output_dir: str, exclude_file_path: str = None):
    if exclude_file_path != None:
        command = f"ssh -p {sshport} -oStrictHostKeyChecking=no {constants.CDSW_ROOT_USER} \"du -sh -k --exclude-from='{constants.EXCLUDE_FILE_ROOT_PATH}'\""
    else:
        command = f'ssh -p {sshport} -oStrictHostKeyChecking=no {constants.CDSW_ROOT_USER} "du -sh -k ."'
    output = subprocess.check_output(command, shell=True).decode("utf-8").strip()
    # Extract the file size from the output
    file_size = output.split("\t")[0]
    s = os.statvfs(output_dir)
    localdir_size = (s.f_bavail * s.f_frsize) / 1024
    if float(file_size) > float(localdir_size):
        logging.error(
            "Insufficient disk storage to download project files for the project."
        )
        raise RuntimeError


class ProjectExporter(BaseWorkspaceInteractor):
    def __init__(
        self,
        host: str,
        username: str,
        project_name: str,
        api_key: str,
        top_level_dir: str,
        ca_path: str,
        project_slug: str,
        owner_type: str,
    ) -> None:
        self._ssh_subprocess = None
        self.top_level_dir = top_level_dir
        self.project_id = None
        self.owner_type = owner_type
        self._original_owner_username = None  # Cache for owner restoration
        super().__init__(host, username, project_name, api_key, ca_path, project_slug)
        self.metrics_data = dict()

    # Get CDSW project info using API v2
    def get_project_infov2(self, project_id: str = None):
        if project_id is None:
            # First get the project ID by searching for the project
            project_id = self._get_project_id_by_name()
        endpoint = Template(ApiV2Endpoints.GET_PROJECT.value).substitute(
            project_id=project_id
        )
        response = call_api_v2(
            host=self.host,
            endpoint=endpoint,
            method="GET",
            user_token=self.apiv2_key,
            ca_path=self.ca_path,
        )
        return response.json()

    def _get_project_id_by_name(self):
        """Helper method to get project ID by project name using V2 API
        Tries multiple search strategies to find projects including public ones"""
        
        # Strategy 1: Search with name filter (finds owned projects)
        search_option = {"name": self.project_name}
        encoded_option = urllib.parse.quote(
            json.dumps(search_option).replace('"', '"')
        )
        endpoint = Template(ApiV2Endpoints.SEARCH_PROJECT.value).substitute(
            search_option=encoded_option
        )
        response = call_api_v2(
            host=self.host,
            endpoint=endpoint,
            method="GET",
            user_token=self.apiv2_key,
            ca_path=self.ca_path,
        )
        project_list = response.json()["projects"]
        if project_list:
            for project in project_list:
                if project["name"] == self.project_name:
                    return project["id"]
        
        # Strategy 2: List all projects (no filter) - gets all accessible projects including public ones
        logging.info(f"Project {self.project_name} not found in owned projects, searching all accessible projects...")
        endpoint_all = "/api/v2/projects?page_size=1000&sort=-created_at"
        
        try:
            response_all = call_api_v2(
                host=self.host,
                endpoint=endpoint_all,
                method="GET",
                user_token=self.apiv2_key,
                ca_path=self.ca_path,
            )
            all_projects = response_all.json()["projects"]
            
            for project in all_projects:
                if project["name"].lower() == self.project_name.lower():
                    logging.info(f"Found project {self.project_name} in accessible projects list (ID: {project['id']})")
                    return project["id"]
        except Exception as e:
            logging.warning(f"Could not search all accessible projects: {e}")
        
        raise RuntimeError(f"Project {self.project_name} not found in owned or accessible projects")

    # Get CDSW project env variables using API v1
    def get_project_env(self):
        endpoint = Template(ApiV1Endpoints.PROJECT_ENV.value).substitute(
            username=self.username, project_name=self.project_slug
        )
        response = call_api_v1(
            host=self.host,
            endpoint=endpoint,
            method="GET",
            api_key=self.api_key,
            ca_path=self.ca_path,
        )
        return response.json()

    def get_creator_username(self):
        # Use V2 API to search for the project
        search_option = {"name": self.project_name}
        encoded_option = urllib.parse.quote(
            json.dumps(search_option).replace('"', '"')
        )
        endpoint = Template(ApiV2Endpoints.SEARCH_PROJECT.value).substitute(
            search_option=encoded_option
        )
        response = call_api_v2(
            host=self.host,
            endpoint=endpoint,
            method="GET",
            user_token=self.apiv2_key,
            ca_path=self.ca_path,
        )
        project_list = response.json()["projects"]
        
        if project_list:
            for project in project_list:
                if project["name"] == self.project_name:
                    # V2 API structure
                    owner_info = project.get("owner", {})
                    creator_info = project.get("creator", {})
                    
                    # V2 API uses project name as slug (V1 had slug_raw field but V2 doesn't)
                    project_slug = project.get("slug") or project.get("slug_raw") or self.project_name
                    
                    if owner_info.get("type") == constants.ORGANIZATION_TYPE:
                        return (
                            owner_info.get("username"),
                            project_slug,
                            constants.ORGANIZATION_TYPE,
                        )
                    else:
                        return (
                            creator_info.get("username"),
                            project_slug,
                            constants.USER_TYPE,
                        )
        return None, None, None

    # Get all models list info using API v2
    def get_models_listv2(self, project_id: str):
        endpoint = Template(ApiV2Endpoints.MODELS_LIST.value).substitute(
            project_id=project_id
        )
        response = call_api_v2(
            host=self.host,
            endpoint=endpoint,
            method="GET",
            user_token=self.apiv2_key,
            ca_path=self.ca_path,
        )
        return response.json().get("models", [])

    # Get all jobs list info using API v2
    def get_jobs_listv2(self, project_id: str):
        endpoint = Template(ApiV2Endpoints.JOBS_LIST.value).substitute(
            project_id=project_id
        )
        response = call_api_v2(
            host=self.host,
            endpoint=endpoint,
            method="GET",
            user_token=self.apiv2_key,
            ca_path=self.ca_path,
        )
        return response.json().get("jobs", [])

    # Get all applications list info using API v2
    def get_app_listv2(self, project_id: str):
        endpoint = Template(ApiV2Endpoints.APPS_LIST.value).substitute(
            project_id=project_id
        )
        response = call_api_v2(
            host=self.host,
            endpoint=endpoint,
            method="GET",
            user_token=self.apiv2_key,
            ca_path=self.ca_path,
        )
        return response.json().get("applications", [])

    # Get CDSW model info using API v2
    def get_model_infov2(self, project_id: str, model_id: str):
        endpoint = Template(ApiV2Endpoints.BUILD_MODEL.value).substitute(
            project_id=project_id, model_id=model_id
        )
        response = call_api_v2(
            host=self.host,
            endpoint=endpoint,
            method="GET",
            user_token=self.apiv2_key,
            ca_path=self.ca_path,
        )
        return response.json()

    # Get current user info
    def get_current_user_info(self):
        """Get the user information - we already have the username"""
        # We don't need an API call - we already have the username
        return {"username": self.username}

    # Update project owner using V2 API
    def update_project_owner(self, project_id: str, new_owner_username: str):
        """
        Update the project owner using V2 API PATCH endpoint
        
        Args:
            project_id: The project ID
            new_owner_username: The username of the new owner
        """
        endpoint = Template(ApiV2Endpoints.UPDATE_PROJECT.value).substitute(
            project_id=project_id
        )
        json_data = {
            "owner": {
                "username": new_owner_username
            }
        }
        logging.info(f"Updating project {project_id} owner to: {new_owner_username}")
        response = call_api_v2(
            host=self.host,
            endpoint=endpoint,
            method="PATCH",
            user_token=self.apiv2_key,
            json_data=json_data,
            ca_path=self.ca_path,
        )
        return response.json()

    # Temporarily change project owner for export/import operations
    def temporarily_change_owner_to_admin(self, project_id: str):
        """
        Temporarily change project owner to the current admin user.
        Caches the original owner for later restoration.
        
        Args:
            project_id: The project ID
            
        Returns:
            bool: True if owner was changed, False if already owned by current user
        """
        # Get current project info
        project_info = self.get_project_infov2(project_id=project_id)
        current_owner = project_info.get("owner", {}).get("username")
        
        # Get current user (admin) info
        current_user = self.get_current_user_info()
        admin_username = current_user.get("username")
        
        logging.info(f"Current project owner: {current_owner}, Admin user: {admin_username}")
        
        # If already owned by admin, no need to change
        if current_owner == admin_username:
            logging.info("Project already owned by current admin user, no ownership change needed")
            return False
        
        # Cache original owner
        self._original_owner_username = current_owner
        logging.info(f"Cached original owner: {current_owner}")
        
        # Change owner to admin
        self.update_project_owner(project_id, admin_username)
        logging.info(f"Successfully changed project owner from {current_owner} to {admin_username}")
        return True

    # Restore original project owner
    def restore_original_owner(self, project_id: str):
        """
        Restore the project owner to the original owner.
        
        Args:
            project_id: The project ID
        """
        if self._original_owner_username:
            logging.info(f"Restoring project owner to: {self._original_owner_username}")
            self.update_project_owner(project_id, self._original_owner_username)
            logging.info(f"Successfully restored project owner to {self._original_owner_username}")
            self._original_owner_username = None
        else:
            logging.debug("No original owner cached, skipping restoration")

    # Get all runtimes using API v2
    def get_all_runtimes(self):
        """Get all runtimes using V2 API with pagination"""
        all_runtimes = []
        page_token = ""
        
        while True:
            endpoint = Template(ApiV2Endpoints.RUNTIMES.value).substitute(
                page_size=1000, page_token=page_token
            )
            response = call_api_v2(
                host=self.host,
                endpoint=endpoint,
                method="GET",
                user_token=self.apiv2_key,
                ca_path=self.ca_path,
            )
            result = response.json()
            all_runtimes.extend(result.get("runtimes", []))
            
            # Check if there are more pages
            page_token = result.get("next_page_token", "")
            if not page_token:
                break
        
        return {"runtimes": all_runtimes}

    def terminate_ssh_session(self):
        logging.info("Terminating ssh connection.")
        if self._ssh_subprocess is not None:
            self._ssh_subprocess.send_signal(signal.SIGINT)
        self._ssh_subprocess = None

    def transfer_project_files(self, log_filedir: str):
        owner_changed = False
        try:
            # Get project ID and temporarily change owner if needed
            if not self.project_id:
                # Get project ID from V2 API
                project_info = self.get_project_infov2()
                self.project_id = project_info["id"]
            
            # Temporarily change owner to admin for file transfer
            logging.info("Checking if project owner change is needed for file transfer...")
            owner_changed = self.temporarily_change_owner_to_admin(self.project_id)
            
            rsync_enabled_runtime_id = -1
            project_uses_runtimes = is_project_configured_with_runtimes(
                host=self.host,
                username=self.username,
                project_name=self.project_name,
                api_key=self.api_key,
                ca_path=self.ca_path,
                project_slug=self.project_slug,
            )
            if project_uses_runtimes:
                rsync_enabled_runtime_id = get_rsync_enabled_runtime_id(
                    host=self.host, api_key=self.api_key, ca_path=self.ca_path
                )
                if rsync_enabled_runtime_id == -1:
                    logging.error("Project is configured with runtimes but no runtime available for SSH session")
                    raise RuntimeError("Cannot create SSH session: no runtime available")
            cdswctl_path = obtain_cdswctl(host=self.host, ca_path=self.ca_path)
            login_response = cdswctl_login(
                cdswctl_path=cdswctl_path,
                host=self.host,
                username=self.username,
                api_key=self.api_key,
                ca_path=self.ca_path,
            )
            if login_response.returncode != 0:
                logging.error("Cdswctl login failed")
                raise RuntimeError
            project_data_dir, _ = ensure_project_data_and_metadata_directory_exists(
                self.top_level_dir, self.project_name
            )

            logging.info("Creating SSH connection")
            ssh_subprocess, port = open_ssh_endpoint(
                cdswctl_path=cdswctl_path,
                project_name=self.project_name,
                runtime_id=rsync_enabled_runtime_id,
                project_slug=self.project_slug,
            )
            self._ssh_subprocess = ssh_subprocess
            exclude_file_path = get_ignore_files(
                host=self.host,
                username=self.username,
                project_name=self.project_name,
                api_key=self.api_key,
                ca_path=self.ca_path,
                ssh_port=port,
                project_slug=self.project_slug,
                top_level_dir=self.top_level_dir,
            )
            test_file_size(
                sshport=port,
                output_dir=project_data_dir,
                exclude_file_path=exclude_file_path,
            )
            transfer_project_files(
                sshport=port,
                source=constants.CDSW_PROJECTS_ROOT_DIR,
                destination=project_data_dir,
                retry_limit=3,
                project_name=self.project_name,
                exclude_file_path=exclude_file_path,
                log_filedir=log_filedir,
            )
            self.remove_cdswctl_dir(cdswctl_path)
            self.terminate_ssh_session()
        finally:
            # Always restore owner if it was changed, even if export fails
            # dump_project_and_related_metadata() will also check, but this ensures restoration on failure
            if self.project_id and self._original_owner_username:
                try:
                    logging.info("Restoring owner after file transfer failure/completion")
                    self.restore_original_owner(self.project_id)
                except Exception as e:
                    logging.error(f"Failed to restore original project owner: {e}")
                    # Log error but don't fail - the export already failed

    def verify_project_files(self, log_filedir: str):
        rsync_enabled_runtime_id = -1
        if is_project_configured_with_runtimes(
            host=self.host,
            username=self.username,
            project_name=self.project_name,
            api_key=self.api_key,
            ca_path=self.ca_path,
            project_slug=self.project_slug,
        ):
            rsync_enabled_runtime_id = get_rsync_enabled_runtime_id(
                host=self.host, api_key=self.api_key, ca_path=self.ca_path
            )
        cdswctl_path = obtain_cdswctl(host=self.host, ca_path=self.ca_path)
        login_response = cdswctl_login(
            cdswctl_path=cdswctl_path,
            host=self.host,
            username=self.username,
            api_key=self.api_key,
            ca_path=self.ca_path,
        )
        if login_response.returncode != 0:
            logging.error("Cdswctl login failed")
            raise RuntimeError

        logging.info("Creating SSH connection")
        ssh_subprocess, port = open_ssh_endpoint(
            cdswctl_path=cdswctl_path,
            project_name=self.project_name,
            runtime_id=rsync_enabled_runtime_id,
            project_slug=self.project_slug,
        )
        self._ssh_subprocess = ssh_subprocess
        exclude_file_path = get_ignore_files(
            host=self.host,
            username=self.username,
            project_name=self.project_name,
            api_key=self.api_key,
            ca_path=self.ca_path,
            ssh_port=port,
            project_slug=self.project_slug,
            top_level_dir=self.top_level_dir,
        )
        result = verify_files(
            sshport=port,
            source=os.path.join(
                get_project_data_dir_path(
                    top_level_dir=self.top_level_dir, project_name=self.project_name
                ),
                "",
            ),
            destination=constants.CDSW_PROJECTS_ROOT_DIR,
            retry_limit=3,
            project_name=self.project_name,
            exclude_file_path=exclude_file_path,
            log_filedir=log_filedir,
        )
        self.remove_cdswctl_dir(cdswctl_path)
        self.terminate_ssh_session()
        return result

    def _export_project_metadata(self):
        filepath = get_project_metadata_file_path(
            top_level_dir=self.top_level_dir, project_name=self.project_name
        )
        logging.info("Exporting project metadata to path %s", filepath)
        
        verbose = os.environ.get('CMLUTILS_VERBOSE', 'False').lower() == 'true'
        if verbose:
            logging.debug("Fetching project information for project: %s", self.project_name)
        
        # Use V2 API to get project info
        project_info_resp = self.get_project_infov2()
        
        if verbose:
            logging.debug("Fetching project environment variables for project: %s", self.project_name)
        
        # Still need V1 for environment variables as V2 doesn't have a separate endpoint
        project_env = self.get_project_env()
        if "CDSW_APP_POLLING_ENDPOINT" not in project_env:
            project_env["CDSW_APP_POLLING_ENDPOINT"] = "."
        project_info_flatten = flatten_json_data(project_info_resp)
        
        # Use PROJECT_MAPV2 for V2 API response structure
        project_metadata = extract_fields(project_info_flatten, constants.PROJECT_MAPV2)

        if project_info_flatten.get(
            "default_project_engine_type"
        ) == constants.LEGACY_ENGINE and not bool(
            legacy_engine_runtime_constants.engine_to_runtime_map()
        ):
            project_metadata["default_project_engine_type"] = constants.LEGACY_ENGINE

        project_metadata["template"] = "blank"
        project_metadata["environment"] = project_env

        # Create project in team context
        if self.owner_type == constants.ORGANIZATION_TYPE:
            project_metadata["team_name"] = self.username
            logging.warning(
                "Project %s belongs to team %s. Ensure that the team already exists in the target workspace prior to executing the import command.",
                self.project_name,
                self.username,
            )
        self.project_id = project_info_resp["id"]
        write_json_file(file_path=filepath, json_data=project_metadata)

    def _export_models_metadata(self):
        filepath = get_models_metadata_file_path(
            top_level_dir=self.top_level_dir, project_name=self.project_name
        )
        logging.info("Exporting models metadata to path %s", filepath)
        
        verbose = os.environ.get('CMLUTILS_VERBOSE', 'False').lower() == 'true'
        if verbose:
            logging.debug("Fetching models list for project: %s (project_id: %s)", 
                         self.project_name, self.project_id)
        
        # Use V2 API to get models list
        model_list = self.get_models_listv2(project_id=self.project_id)
        model_name_list = []
        if len(model_list) == 0:
            logging.info("Models are not present in the project %s.", self.project_name)
        elif verbose:
            logging.debug("Found %d models in project %s", len(model_list), self.project_name)
        runtime_list = self.get_all_runtimes()
        model_metadata_list = []
        for model in model_list:
            # Get detailed model info including builds
            model_details = self.get_model_infov2(project_id=self.project_id, model_id=model["id"])
            
            model_metadata = {
                "name": model.get("name", ""),
                "description": model.get("description", "")
            }
            model_name_list.append(model_metadata["name"])
            
            if "auth_enabled" in model:
                model_metadata["disable_authentication"] = not model["auth_enabled"]
            
            # Extract build information if available
            if model_details.get("model_builds") and len(model_details["model_builds"]) > 0:
                latest_build = model_details["model_builds"][0]
                build_info_flatten = flatten_json_data(latest_build)
                build_metadata = extract_fields(build_info_flatten, constants.MODEL_MAPV2)
                model_metadata.update(build_metadata)
                
                if "runtime_id" in build_info_flatten:
                    runtime_obj = find_runtime(
                        runtime_list=runtime_list["runtimes"],
                        runtime_id=build_info_flatten["runtime_id"],
                    )
                    if runtime_obj != None:
                        model_metadata.update(runtime_obj)
                elif build_info_flatten.get("kernel"):
                    # Handle legacy engine
                    if bool(legacy_engine_runtime_constants.engine_to_runtime_map()):
                        runtime_identifier = legacy_engine_runtime_constants.engine_to_runtime_map().get(
                            build_info_flatten["kernel"],
                            legacy_engine_runtime_constants.engine_to_runtime_map().get("default")
                        )
                        model_metadata["runtime_identifier"] = runtime_identifier
                    else:
                        model_metadata["kernel"] = build_info_flatten["kernel"]
                else:
                    if bool(legacy_engine_runtime_constants.engine_to_runtime_map()):
                        model_metadata["runtime_identifier"] = legacy_engine_runtime_constants.engine_to_runtime_map().get("default")

            model_metadata_list.append(model_metadata)
        write_json_file(file_path=filepath, json_data=model_metadata_list)
        self.metrics_data["total_model"] = len(model_name_list)
        self.metrics_data["model_name_list"] = sorted(model_name_list)

    def _create_placeholder_files_for_system_scripts(self, app_metadata_list):
        """Create placeholder files for system scripts to enable migration"""
        import os
        
        project_files_dir = get_project_data_dir_path(
            top_level_dir=self.top_level_dir, project_name=self.project_name
        )
        
        for app_metadata in app_metadata_list:
            script_path = app_metadata.get("script", "")
            app_name = app_metadata.get("name", "unknown")
            
            # Check if this is a system script (absolute path starting with /)
            if script_path and script_path.startswith("/"):
                # Convert absolute path to relative (remove leading /)
                relative_script_path = script_path.lstrip("/")
                
                # Create full path in export directory
                full_export_path = os.path.join(project_files_dir, relative_script_path)
                
                # Create directories if they don't exist
                os.makedirs(os.path.dirname(full_export_path), exist_ok=True)
                
                # Create placeholder file
                placeholder_content = f"""#!/usr/bin/env python3
'''
MIGRATION PLACEHOLDER for {app_name}

This file was automatically created during project export to enable migration
of applications with system-level scripts.

Original script path: {script_path}
Application: {app_name}

IMPORTANT:
This is a placeholder. The actual application uses a script from the runtime
container. After migration:
1. The application will be created successfully
2. Update the script path in CML UI back to: {script_path}
3. Or keep this placeholder and add your own application code here

For Data Visualization apps, the system script will work automatically once
the path is updated back to the original: {script_path}
'''

print(f"Placeholder for {app_name}")
print(f"Original script: {script_path}")
print("Please update the application script path in CML UI")
"""
                
                try:
                    with open(full_export_path, 'w') as f:
                        f.write(placeholder_content)
                    logging.info(f"✅ Created placeholder for system script: {relative_script_path}")
                except Exception as e:
                    logging.warning(f"Could not create placeholder for {script_path}: {e}")
    
    def _export_application_metadata(self):
        filepath = get_applications_metadata_file_path(
            top_level_dir=self.top_level_dir, project_name=self.project_name
        )
        logging.info("Exporting application metadata to path %s", filepath)
        # Use V2 API to get applications list
        app_list = self.get_app_listv2(project_id=self.project_id)
        app_name_list = []
        if len(app_list) == 0:
            logging.info(
                "Applications are not present in the project %s.", self.project_name
            )
        app_metadata_list = []
        for app in app_list:
            app_info_flatten = flatten_json_data(app)
            # Use APPLICATION_MAPV2 for V2 API response structure
            app_metadata = extract_fields(app_info_flatten, constants.APPLICATION_MAPV2)
            app_name_list.append(app_metadata["name"])
            app_metadata["environment"] = app.get("environment", {})
            
            # Capture complete runtime information from V2 API
            runtime_identifier = app.get("runtime_identifier")
            runtime_addons = app.get("runtime_addon_identifiers", [])
            kernel = app.get("kernel", "")
            
            if runtime_identifier:
                app_metadata["runtime_identifier"] = runtime_identifier
                logging.debug(f"Captured runtime_identifier for app '{app_metadata['name']}': {runtime_identifier}")
            
            if runtime_addons:
                app_metadata["runtime_addon_identifiers"] = runtime_addons
                logging.debug(f"Captured runtime addons for app '{app_metadata['name']}': {runtime_addons}")
            
            if kernel:
                app_metadata["kernel"] = kernel
            
            # Fallback to legacy engine mapping if no runtime_identifier captured
            if not runtime_identifier:
                legacy_kernel = app_info_flatten.get("runtime.kernel") or app_info_flatten.get("kernel")
                if legacy_kernel and bool(legacy_engine_runtime_constants.engine_to_runtime_map()):
                    runtime_identifier = (
                        legacy_engine_runtime_constants.engine_to_runtime_map().get(
                            legacy_kernel,
                            legacy_engine_runtime_constants.engine_to_runtime_map().get("default"),
                        )
                    )
                    app_metadata["runtime_identifier"] = runtime_identifier
                    app_metadata["kernel"] = legacy_kernel
            
            app_metadata_list.append(app_metadata)

        write_json_file(file_path=filepath, json_data=app_metadata_list)
        self.metrics_data["total_application"] = len(app_metadata_list)
        self.metrics_data["application_name_list"] = sorted(app_name_list)
        
        # Create placeholder files for system scripts to enable migration
        self._create_placeholder_files_for_system_scripts(app_metadata_list)

    def collect_export_job_list(self):
        # Use V2 API to get jobs list
        job_list = self.get_jobs_listv2(project_id=self.project_id)
        job_name_list = []
        if len(job_list) == 0:
            logging.info("Jobs are not present in the project %s.", self.project_name)
        else:
            logging.info("Project {} has {} Jobs".format(self.project_name, len(job_list)))
        job_metadata_list = []
        for job in job_list:
            job_info_flatten = flatten_json_data(job)
            job_metadata = extract_fields(job_info_flatten, constants.JOB_MAP)
            job_name_list.append(job_metadata["name"])
            job_metadata_list.append(job_metadata)
        return job_metadata_list, sorted(job_name_list)

    def collect_export_model_list(self, proj_id):
        # Use V2 API to get models list
        model_list = self.get_models_listv2(project_id=proj_id)
        model_name_list = []
        if len(model_list) == 0:
            logging.info("Models are not present in the project %s.", self.project_name)
        else:
            logging.info("Project {} has {} Models".format(self.project_name, len(model_list)))
        model_metadata_list = []
        for model in model_list:
            model_metadata = {
                "name": model.get("name", ""),
                "description": model.get("description", "")
            }
            model_name_list.append(model_metadata["name"])
            model_metadata_list.append(model_metadata)
        return model_metadata_list, sorted(model_name_list)

    def collect_export_application_list(self):
        # Use V2 API to get applications list
        app_list = self.get_app_listv2(project_id=self.project_id)
        app_name_list = []
        if len(app_list) == 0:
            logging.info(
                "Applications are not present in the project %s.", self.project_name
            )
        else:
            logging.info("Project {} has {} Applications".format(self.project_name, len(app_list)))
        app_metadata_list = []
        for app in app_list:
            app_info_flatten = flatten_json_data(app)
            app_metadata = extract_fields(app_info_flatten, constants.APPLICATION_MAPV2)
            app_name_list.append(app_metadata["name"])
            project_env = self.get_project_env()
            if not app_metadata.get("environment"):
                app_metadata["environment"] = project_env
            app_metadata_list.append(app_metadata)
        return app_metadata_list, sorted(app_name_list)

    def _export_job_metadata(self):
        filepath = get_jobs_metadata_file_path(
            top_level_dir=self.top_level_dir, project_name=self.project_name
        )
        logging.info("Exporting job metadata to path %s ", filepath)
        # Use V2 API to get jobs list
        job_list = self.get_jobs_listv2(project_id=self.project_id)
        if len(job_list) == 0:
            logging.info("Jobs are not present in the project %s.", self.project_name)
        runtime_list = self.get_all_runtimes()
        job_metadata_list = []
        job_name_list = []

        for job in job_list:
            job_info_flatten = flatten_json_data(job)
            job_metadata = extract_fields(job_info_flatten, constants.JOB_MAP)
            job_name_list.append(job_metadata["name"])
            job_metadata["attachments"] = job.get("report", {}).get("attachments", [])
            job_metadata["environment"] = job.get("environment", {})
            
            # Check for runtime information
            if "runtime.id" in job_info_flatten or "runtime_id" in job_info_flatten:
                runtime_id = job_info_flatten.get("runtime.id") or job_info_flatten.get("runtime_id")
                runtime_obj = find_runtime(
                    runtime_list=runtime_list["runtimes"],
                    runtime_id=runtime_id,
                )
                if runtime_obj != None:
                    job_metadata.update(runtime_obj)
                else:
                    job_metadata[
                        "runtime_identifier"
                    ] = legacy_engine_runtime_constants.engine_to_runtime_map().get(
                        "default"
                    )
            else:
                # Handle legacy engine
                kernel = job_info_flatten.get("kernel")
                if kernel:
                    if bool(legacy_engine_runtime_constants.engine_to_runtime_map()):
                        runtime_identifier = legacy_engine_runtime_constants.engine_to_runtime_map().get(
                            kernel,
                            legacy_engine_runtime_constants.engine_to_runtime_map().get("default")
                        )
                        job_metadata["runtime_identifier"] = runtime_identifier
                    else:
                        job_metadata["kernel"] = kernel
                else:
                    if bool(legacy_engine_runtime_constants.engine_to_runtime_map()):
                        job_metadata[
                            "runtime_identifier"
                        ] = legacy_engine_runtime_constants.engine_to_runtime_map().get(
                            "default"
                        )

            job_metadata_list.append(job_metadata)

        write_json_file(file_path=filepath, json_data=job_metadata_list)
        self.metrics_data["total_job"] = len(job_name_list)
        self.metrics_data["job_name_list"] = sorted(job_name_list)

    def dump_project_and_related_metadata(self):
        owner_changed = False
        try:
            # Temporarily change owner to admin if needed
            if self.project_id:
                logging.info("Checking if project owner change is needed for export...")
                owner_changed = self.temporarily_change_owner_to_admin(self.project_id)
            
            self._export_project_metadata()
            self._export_models_metadata()
            self._export_application_metadata()
            self._export_job_metadata()
            return self.metrics_data
        finally:
            # Always restore original owner if we have one cached (even if owner_changed is False)
            # This handles the case where owner was changed in transfer_project_files() but not here
            if self.project_id and self._original_owner_username:
                try:
                    self.restore_original_owner(self.project_id)
                except Exception as e:
                    logging.error(f"Failed to restore original project owner: {e}")
                    # Don't fail the export, but log the error

    def collect_export_project_data(self):
        # Use V2 API to get project info
        proj_data_raw = self.get_project_infov2()
        proj_info_flatten = flatten_json_data(proj_data_raw)
        proj_data = [extract_fields(proj_info_flatten, constants.PROJECT_MAPV2)]
        proj_list = [self.project_name.lower()]
        if not proj_data[0].get("shared_memory_limit"):
            proj_data[0]["shared_memory_limit"] = 0

        model_data, model_list = self.collect_export_model_list(
            proj_data_raw["id"]
        )
        app_data, app_list = self.collect_export_application_list()
        job_data, job_list = self.collect_export_job_list()
        return (
            proj_data,
            proj_list,
            model_data,
            model_list,
            app_data,
            app_list,
            job_data,
            job_list,
        )


class ProjectImporter(BaseWorkspaceInteractor):
    def __init__(
        self,
        host: str,
        username: str,
        project_name: str,
        api_key: str,
        top_level_dir: str,
        ca_path: str,
        project_slug: str,
    ) -> None:
        self._ssh_subprocess = None
        self.top_level_dir = top_level_dir
        self.project_id = None  # Will be populated from API
        self._original_owner_username = None  # Cache for owner restoration
        super().__init__(host, username, project_name, api_key, ca_path, project_slug)
        self.metrics_data = dict()
        # Track import outcomes for applications
        self.import_tracking = {
            "apps_imported_successfully": [],
            "apps_removed_from_manifest": [],
            "apps_skipped": [],
            "apps_imported_with_fallback": []
        }

    def get_creator_username(self):
        # Use V2 API to search for the project with enhanced search for team/shared projects
        search_option = {"name": self.project_name}
        encoded_option = urllib.parse.quote(
            json.dumps(search_option).replace('"', '"')
        )
        endpoint = Template(ApiV2Endpoints.SEARCH_PROJECT.value).substitute(
            search_option=encoded_option
        )
        response = call_api_v2(
            host=self.host,
            endpoint=endpoint,
            method="GET",
            user_token=self.apiv2_key,
            ca_path=self.ca_path,
        )
        project_list = response.json()["projects"]
        
        if project_list:
            for project in project_list:
                if project["name"] == self.project_name:
                    creator_info = project.get("creator", {})
                    # V2 API uses project name as slug (V1 had slug_raw field but V2 doesn't)
                    project_slug = project.get("slug") or project.get("slug_raw") or self.project_name
                    return creator_info.get("username"), project_slug
        
        # Enhanced search: List all accessible projects (including team/shared projects)
        logging.info(f"Project {self.project_name} not found in basic search, trying all accessible projects...")
        endpoint_all = "/api/v2/projects?page_size=1000&sort=-created_at"
        
        try:
            response_all = call_api_v2(
                host=self.host,
                endpoint=endpoint_all,
                method="GET",
                user_token=self.apiv2_key,
                ca_path=self.ca_path,
            )
            all_projects = response_all.json()["projects"]
            
            for project in all_projects:
                if project["name"].lower() == self.project_name.lower():
                    logging.info(f"Found project {self.project_name} in accessible projects (team/shared)")
                    creator_info = project.get("creator", {})
                    project_slug = project.get("slug") or project.get("slug_raw") or self.project_name
                    return creator_info.get("username"), project_slug
        except Exception as e:
            logging.warning(f"Could not search all accessible projects: {e}")
        
        return None, None

    def transfer_project(self, log_filedir: str, verify=False):
        owner_changed = False
        result = None
        try:
            # Get project slug and ID from creator info
            if not self.project_slug:
                creator_username, project_slug = self.get_creator_username()
                if project_slug:
                    self.project_slug = project_slug
                else:
                    self.project_slug = self.project_name.lower()
            
            # Get project ID if not already set
            if not self.project_id:
                creator_username, project_slug = self.get_creator_username()
                # Search for project to get ID using V2 API with enhanced search
                from datetime import datetime, timedelta
                import json
                import urllib.parse
                
                # First try with name filter
                search_filter = json.dumps({'name': self.project_name})
                endpoint = f'/api/v2/projects?search_filter={urllib.parse.quote(search_filter)}&page_size=50&sort=-created_at'
                
                response = call_api_v2(
                    host=self.host,
                    endpoint=endpoint,
                    method="GET",
                    user_token=self.apiv2_key,
                    ca_path=self.ca_path,
                )
                project_list = response.json().get("projects", [])
                
                for project in project_list:
                    if project["name"].lower() == self.project_name.lower():
                        self.project_id = project["id"]
                        if not self.project_slug:
                            self.project_slug = project.get("slug") or project.get("slug_raw") or self.project_name.lower()
                        break
                
                # If not found, try enhanced search (all accessible projects including team/shared)
                if not self.project_id:
                    logging.info(f"Project {self.project_name} not found with name filter, searching all accessible projects...")
                    endpoint_all = "/api/v2/projects?page_size=1000&sort=-created_at"
                    
                    try:
                        response_all = call_api_v2(
                            host=self.host,
                            endpoint=endpoint_all,
                            method="GET",
                            user_token=self.apiv2_key,
                            ca_path=self.ca_path,
                        )
                        all_projects = response_all.json().get("projects", [])
                        
                        for project in all_projects:
                            if project["name"].lower() == self.project_name.lower():
                                self.project_id = project["id"]
                                if not self.project_slug:
                                    self.project_slug = project.get("slug") or project.get("slug_raw") or self.project_name.lower()
                                logging.info(f"Found project {self.project_name} in accessible projects (ID: {self.project_id})")
                                break
                    except Exception as e:
                        logging.warning(f"Could not search all accessible projects: {e}")
            
            # Temporarily change owner to current user for file transfer
            if self.project_id:
                logging.info("Checking if project owner change is needed for import file transfer...")
                owner_changed = self.temporarily_change_owner_to_admin(self.project_id)
            else:
                logging.info("Project ID not found, proceeding without owner change (new project will be created)")
            
            rsync_enabled_runtime_id = get_rsync_enabled_runtime_id(
                host=self.host, api_key=self.apiv2_key, ca_path=self.ca_path
            )
            cdswctl_path = obtain_cdswctl(host=self.host, ca_path=self.ca_path)
            login_response = cdswctl_login(
                cdswctl_path=cdswctl_path,
                host=self.host,
                username=self.username,
                api_key=self.api_key,
                ca_path=self.ca_path,
            )
            if login_response.returncode != 0:
                logging.error("Cdswctl login failed")
                raise RuntimeError
            ssh_subprocess, port = open_ssh_endpoint(
                cdswctl_path=cdswctl_path,
                project_name=self.project_name,
                runtime_id=rsync_enabled_runtime_id,
                project_slug=self.project_slug,
            )
            self._ssh_subprocess = ssh_subprocess
            transfer_project_files(
                sshport=port,
                source=os.path.join(
                    get_project_data_dir_path(
                        top_level_dir=self.top_level_dir, project_name=self.project_name
                    ),
                    "",
                ),
                destination=constants.CDSW_PROJECTS_ROOT_DIR,
                retry_limit=3,
                project_name=self.project_name,
                log_filedir=log_filedir,
            )
            if verify:
                result = verify_files(
                    sshport=port,
                    source=os.path.join(
                        get_project_data_dir_path(
                            top_level_dir=self.top_level_dir, project_name=self.project_name
                        ),
                        "",
                    ),
                    destination=constants.CDSW_PROJECTS_ROOT_DIR,
                    retry_limit=3,
                    project_name=self.project_name,
                    log_filedir=log_filedir,
                )
            
            self.remove_cdswctl_dir(cdswctl_path)
            self.terminate_ssh_session()
            return result
        finally:
            # Always restore owner if it was changed, even if import fails
            if self.project_id and self._original_owner_username:
                try:
                    logging.info("Restoring owner after import file transfer")
                    self.restore_original_owner(self.project_id)
                except Exception as e:
                    logging.error(f"Failed to restore original project owner: {e}")
                    # Log error but don't fail - the import already failed
            
            # Always terminate SSH session to prevent leaks
            if self._ssh_subprocess is not None:
                try:
                    self.terminate_ssh_session()
                except Exception as e:
                    logging.error(f"Failed to terminate SSH session: {e}")

    def verify_project(self, log_filedir: str):
        rsync_enabled_runtime_id = get_rsync_enabled_runtime_id(
            host=self.host, api_key=self.apiv2_key, ca_path=self.ca_path
        )
        cdswctl_path = obtain_cdswctl(host=self.host, ca_path=self.ca_path)
        login_response = cdswctl_login(
            cdswctl_path=cdswctl_path,
            host=self.host,
            username=self.username,
            api_key=self.api_key,
            ca_path=self.ca_path,
        )
        if login_response.returncode != 0:
            logging.error("Cdswctl login failed")
            raise RuntimeError
        ssh_subprocess, port = open_ssh_endpoint(
            cdswctl_path=cdswctl_path,
            project_name=self.project_name,
            runtime_id=rsync_enabled_runtime_id,
            project_slug=self.project_slug,
        )
        self._ssh_subprocess = ssh_subprocess
        result = verify_files(
            sshport=port,
            source=os.path.join(
                get_project_data_dir_path(
                    top_level_dir=self.top_level_dir, project_name=self.project_name
                ),
                "",
            ),
            destination=constants.CDSW_PROJECTS_ROOT_DIR,
            retry_limit=3,
            project_name=self.project_name,
            log_filedir=log_filedir,
        )
        self.remove_cdswctl_dir(cdswctl_path)
        return result

    def terminate_ssh_session(self):
        logging.info("Terminating ssh connection.")
        if self._ssh_subprocess is not None:
            self._ssh_subprocess.send_signal(signal.SIGINT)
        self._ssh_subprocess = None

    def create_project_v2(self, proj_metadata) -> str:
        try:
            endpoint = ApiV2Endpoints.PROJECTS.value
            response = call_api_v2(
                host=self.host,
                endpoint=endpoint,
                method="POST",
                user_token=self.apiv2_key,
                json_data=proj_metadata,
                ca_path=self.ca_path,
            )
            json_resp = response.json()
            return json_resp["id"]
        except KeyError as e:
            logging.error(f"Error: {e}")
            raise

    def convert_project_to_engine_based(self, proj_patch_metadata) -> bool:
        try:
            endpoint2 = Template(ApiV1Endpoints.PROJECT.value).substitute(
                username=self.username, project_name=self.project_name
            )
            response = call_api_v1(
                host=self.host,
                endpoint=endpoint2,
                method="PATCH",
                api_key=self.api_key,
                json_data=proj_patch_metadata,
                ca_path=self.ca_path,
            )
            return True
        except KeyError as e:
            logging.error(f"Error: {e}")
            raise

    def create_model_v2(self, proj_id: str, model_metadata) -> str:
        try:
            endpoint = Template(ApiV2Endpoints.CREATE_MODEL.value).substitute(
                project_id=proj_id
            )
            response = call_api_v2(
                host=self.host,
                endpoint=endpoint,
                method="POST",
                user_token=self.apiv2_key,
                json_data=model_metadata,
                ca_path=self.ca_path,
            )
            json_resp = response.json()
            return json_resp["id"]
        except KeyError as e:
            logging.error(f"Error: {e}")
            raise

    def create_model_build_v2(
        self, proj_id: str, model_id: str, model_metadata
    ) -> None:
        endpoint = Template(ApiV2Endpoints.BUILD_MODEL.value).substitute(
            project_id=proj_id, model_id=model_id
        )
        response = call_api_v2(
            host=self.host,
            endpoint=endpoint,
            method="POST",
            user_token=self.apiv2_key,
            json_data=model_metadata,
            ca_path=self.ca_path,
        )
        return

    def create_application_v2(self, proj_id: str, app_metadata) -> str:
        try:
            endpoint = Template(ApiV2Endpoints.CREATE_APP.value).substitute(
                project_id=proj_id
            )
            response = call_api_v2(
                host=self.host,
                endpoint=endpoint,
                method="POST",
                user_token=self.apiv2_key,
                json_data=app_metadata,
                ca_path=self.ca_path,
            )
            json_resp = response.json()
            return json_resp["id"]
        except KeyError as e:
            logging.error(f"Error: {e}")
            raise

    def stop_application_v2(self, proj_id: str, app_id: str) -> None:
        endpoint = Template(ApiV2Endpoints.STOP_APP.value).substitute(
            project_id=proj_id, application_id=app_id
        )
        response = call_api_v2(
            host=self.host,
            endpoint=endpoint,
            method="POST",
            user_token=self.apiv2_key,
            ca_path=self.ca_path,
        )
        return

    def create_job_v2(self, proj_id: str, job_metadata) -> str:
        try:
            endpoint = Template(ApiV2Endpoints.CREATE_JOB.value).substitute(
                project_id=proj_id
            )
            response = call_api_v2(
                host=self.host,
                endpoint=endpoint,
                method="POST",
                user_token=self.apiv2_key,
                json_data=job_metadata,
                ca_path=self.ca_path,
            )
            json_resp = response.json()
            return json_resp["id"]
        except KeyError as e:
            logging.error(f"Error: {e}")
            raise

    def update_job_v2(self, proj_id: str, job_id: str, job_metadata) -> None:
        endpoint = Template(ApiV2Endpoints.UPDATE_JOB.value).substitute(
            project_id=proj_id, job_id=job_id
        )
        response = call_api_v2(
            host=self.host,
            endpoint=endpoint,
            method="PATCH",
            user_token=self.apiv2_key,
            json_data=job_metadata,
            ca_path=self.ca_path,
        )
        return

    # Get all runtimes using API v2
    def get_all_runtimes(self):
        """Get all runtimes using V2 API with pagination"""
        all_runtimes = []
        page_token = ""
        
        while True:
            endpoint = Template(ApiV2Endpoints.RUNTIMES.value).substitute(
                page_size=1000, page_token=page_token
            )
            response = call_api_v2(
                host=self.host,
                endpoint=endpoint,
                method="GET",
                user_token=self.apiv2_key,
                ca_path=self.ca_path,
            )
            result = response.json()
            all_runtimes.extend(result.get("runtimes", []))
            
            # Check if there are more pages
            page_token = result.get("next_page_token", "")
            if not page_token:
                break
        
        return {"runtimes": all_runtimes}

    # Get spark runtime addons using API v2
    def get_spark_runtimeaddons(self):
        search_option = {"identifier": constants.SPARK_ADDON, "status": "AVAILABLE"}
        encoded_option = urllib.parse.quote(json.dumps(search_option).replace('"', '"'))
        endpoint = Template(ApiV2Endpoints.RUNTIME_ADDONS.value).substitute(
            search_option=encoded_option
        )
        response = call_api_v2(
            host=self.host,
            endpoint=endpoint,
            method="GET",
            user_token=self.apiv2_key,
            ca_path=self.ca_path,
        )
        result_list = response.json()["runtime_addons"]
        if result_list:
            return result_list[0]["identifier"]
        return None

    def get_all_runtimes_v2(self, page_token=""):
        endpoint = Template(ApiV2Endpoints.RUNTIMES.value).substitute(
            page_size=constants.MAX_API_PAGE_LENGTH, page_token=page_token
        )

        response = call_api_v2(
            host=self.host,
            endpoint=endpoint,
            method="GET",
            user_token=self.apiv2_key,
            ca_path=self.ca_path,
        )
        result_list = response.json()
        if result_list:
            return result_list
        return None

    def check_project_exist(self, project_name: str) -> str:
        try:
            search_option = {"name": project_name}
            encoded_option = urllib.parse.quote(
                json.dumps(search_option).replace('"', '"')
            )
            endpoint = Template(ApiV2Endpoints.SEARCH_PROJECT.value).substitute(
                search_option=encoded_option
            )
            response = call_api_v2(
                host=self.host,
                endpoint=endpoint,
                method="GET",
                user_token=self.apiv2_key,
                ca_path=self.ca_path,
            )
            project_list = response.json()["projects"]
            if project_list:
                for project in project_list:
                    if project["name"] == project_name:
                        return project["id"]
            return None
        except KeyError as e:
            logging.error(f"Error: {e}")
            raise

    def check_model_exist(self, model_name: str, proj_id: str) -> bool:
        try:
            search_option = {"name": model_name}
            encoded_option = urllib.parse.quote(
                json.dumps(search_option).replace('"', '"')
            )
            endpoint = Template(ApiV2Endpoints.SEARCH_MODEL.value).substitute(
                project_id=proj_id, search_option=encoded_option
            )
            response = call_api_v2(
                host=self.host,
                endpoint=endpoint,
                method="GET",
                user_token=self.apiv2_key,
                ca_path=self.ca_path,
            )
            model_list = response.json()["models"]
            if model_list:
                for model in model_list:
                    if model["name"] == model_name:
                        return True
            return False
        except KeyError as e:
            logging.error(f"Error: {e}")
            raise

    def check_job_exist(self, job_name: str, script: str, proj_id: str) -> str:
        try:
            search_option = {"name": job_name, "script": script}
            encoded_option = urllib.parse.quote(
                json.dumps(search_option).replace('"', '"')
            )
            endpoint = Template(ApiV2Endpoints.SEARCH_JOB.value).substitute(
                project_id=proj_id, search_option=encoded_option
            )
            response = call_api_v2(
                host=self.host,
                endpoint=endpoint,
                method="GET",
                user_token=self.apiv2_key,
                ca_path=self.ca_path,
            )
            job_list = response.json()["jobs"]
            if job_list:
                for job in job_list:
                    if job["name"] == job_name and job["script"] == script:
                        return job["id"]
            return None
        except KeyError as e:
            logging.error(f"Error: {e}")
            raise

    def check_app_exist(self, subdomain: str, proj_id: str) -> bool:
        try:
            search_option = {"subdomain": subdomain}
            encoded_option = urllib.parse.quote(
                json.dumps(search_option).replace('"', '"')
            )
            endpoint = Template(ApiV2Endpoints.SEARCH_APP.value).substitute(
                project_id=proj_id, search_option=encoded_option
            )
            response = call_api_v2(
                host=self.host,
                endpoint=endpoint,
                method="GET",
                user_token=self.apiv2_key,
                ca_path=self.ca_path,
            )
            app_list = response.json()["applications"]
            if app_list:
                for app in app_list:
                    if app["subdomain"] == subdomain:
                        return True
            return False
        except KeyError as e:
            logging.error(f"Error: {e}")
            raise

    def get_models_listv2(self, proj_id: str):
        endpoint = Template(ApiV2Endpoints.MODELS_LIST.value).substitute(
            project_id=proj_id
        )
        response = call_api_v2(
            host=self.host,
            endpoint=endpoint,
            method="GET",
            user_token=self.apiv2_key,
            ca_path=self.ca_path,
        )
        return response.json()

    def get_models_detailv2(self, proj_id: str, model_id: str):
        endpoint = Template(ApiV2Endpoints.BUILD_MODEL.value).substitute(
            project_id=proj_id, model_id=model_id
        )
        response = call_api_v2(
            host=self.host,
            endpoint=endpoint,
            method="GET",
            user_token=self.apiv2_key,
            ca_path=self.ca_path,
        )
        return response.json()

    def get_jobs_listv2(self, proj_id: str):
        endpoint = Template(ApiV2Endpoints.JOBS_LIST.value).substitute(
            project_id=proj_id
        )
        response = call_api_v2(
            host=self.host,
            endpoint=endpoint,
            method="GET",
            user_token=self.apiv2_key,
            ca_path=self.ca_path,
        )
        return response.json()

    def get_application_listv2(self, proj_id: str):
        endpoint = Template(ApiV2Endpoints.APPS_LIST.value).substitute(
            project_id=proj_id
        )
        response = call_api_v2(
            host=self.host,
            endpoint=endpoint,
            method="GET",
            user_token=self.apiv2_key,
            ca_path=self.ca_path,
        )
        return response.json()

    # Get current user info
    def get_current_user_info(self):
        """Get the user information - we already have the username"""
        # We don't need an API call - we already have the username
        return {"username": self.username}

    # Update project owner using V2 API
    def update_project_owner(self, project_id: str, new_owner_username: str):
        """
        Update the project owner using V2 API PATCH endpoint
        
        Args:
            project_id: The project ID
            new_owner_username: The username of the new owner
        """
        endpoint = Template(ApiV2Endpoints.UPDATE_PROJECT.value).substitute(
            project_id=project_id
        )
        json_data = {
            "owner": {
                "username": new_owner_username
            }
        }
        logging.info(f"Updating project {project_id} owner to: {new_owner_username}")
        response = call_api_v2(
            host=self.host,
            endpoint=endpoint,
            method="PATCH",
            user_token=self.apiv2_key,
            json_data=json_data,
            ca_path=self.ca_path,
        )
        return response.json()

    # Temporarily change project owner for export/import operations
    def temporarily_change_owner_to_admin(self, project_id: str):
        """
        Temporarily change project owner to the current admin user.
        Caches the original owner for later restoration.
        
        Args:
            project_id: The project ID
            
        Returns:
            bool: True if owner was changed, False if already owned by current user
        """
        # Get current project info
        project_info = self.get_project_infov2(proj_id=project_id)
        current_owner = project_info.get("owner", {}).get("username")
        
        # Get current user (admin) info
        current_user = self.get_current_user_info()
        admin_username = current_user.get("username")
        
        logging.info(f"Current project owner: {current_owner}, Admin user: {admin_username}")
        
        # If already owned by admin, no need to change
        if current_owner == admin_username:
            logging.info("Project already owned by current admin user, no ownership change needed")
            return False
        
        # Cache original owner
        self._original_owner_username = current_owner
        logging.info(f"Cached original owner: {current_owner}")
        
        # Change owner to admin
        self.update_project_owner(project_id, admin_username)
        logging.info(f"Successfully changed project owner from {current_owner} to {admin_username}")
        return True

    # Restore original project owner
    def restore_original_owner(self, project_id: str):
        """
        Restore the project owner to the original owner.
        
        Args:
            project_id: The project ID
        """
        if self._original_owner_username:
            logging.info(f"Restoring project owner to: {self._original_owner_username}")
            self.update_project_owner(project_id, self._original_owner_username)
            logging.info(f"Successfully restored project owner to {self._original_owner_username}")
            self._original_owner_username = None
        else:
            logging.debug("No original owner cached, skipping restoration")

    def import_metadata(self, project_id: str):
        owner_changed = False
        try:
            # Temporarily change owner to current user for metadata import
            logging.info("Checking if project owner change is needed for metadata import...")
            owner_changed = self.temporarily_change_owner_to_admin(project_id)
            
            models_metadata_filepath = get_models_metadata_file_path(
                top_level_dir=self.top_level_dir, project_name=self.project_name
            )
            self.create_models(
                project_id=project_id, models_metadata_filepath=models_metadata_filepath
            )

            app_metadata_filepath = get_applications_metadata_file_path(
                top_level_dir=self.top_level_dir, project_name=self.project_name
            )
            self.create_stoppped_applications(
                project_id=project_id, app_metadata_filepath=app_metadata_filepath
            )

            job_metadata_filepath = get_jobs_metadata_file_path(
                top_level_dir=self.top_level_dir, project_name=self.project_name
            )
            self.create_paused_jobs(
                project_id=project_id, job_metadata_filepath=job_metadata_filepath
            )
            self.get_project_infov2(proj_id=project_id)
            self.collect_import_model_list(project_id=project_id)
            self.collect_import_application_list(project_id=project_id)
            self.collect_import_job_list(project_id=project_id)
            
            # Generate manual steps manifest if any applications need attention
            self._generate_manual_steps_manifest()
            
            return self.metrics_data
        finally:
            # Always restore original owner if we have one cached
            if project_id and self._original_owner_username:
                try:
                    logging.info("Restoring owner after metadata import")
                    self.restore_original_owner(project_id)
                except Exception as e:
                    logging.error(f"Failed to restore original project owner: {e}")
                    # Don't fail the import, but log the error

    def _generate_human_readable_report(self, manifest: dict, report_path: str):
        """Generate a human-readable text report for the migration"""
        from datetime import datetime
        
        report_lines = [
            "="*80,
            "PROJECT MIGRATION REPORT",
            "="*80,
            "",
            f"Migration Date: {manifest['migration_date']}",
            f"Target Project: {manifest['target_project']}",
            "",
            "-"*80,
            "",
            "SUMMARY",
            "",
            "Applications:",
            f"  Total Applications: {manifest['summary']['total_applications']}",
            f"  Imported Successfully: {manifest['summary'].get('apps_imported_successfully', manifest['summary'].get('imported_successfully', 0))}",
            f"  Imported with Modifications: {manifest['summary'].get('apps_imported_with_modifications', manifest['summary'].get('imported_with_modifications', 0))}",
            f"  Imported with Fallback Runtime: {manifest['summary'].get('apps_imported_with_fallback', manifest['summary'].get('imported_with_fallback', 0))}",
            f"  Removed from Import: {manifest['summary'].get('apps_removed_from_manifest', manifest['summary'].get('removed_from_manifest', 0))}",
            f"  Skipped: {manifest['summary'].get('apps_skipped', manifest['summary'].get('skipped', 0))}",
            "",
            "Models:",
            f"  Total Models: {manifest['summary'].get('total_models', 0)}",
            f"  Imported Successfully: {manifest['summary'].get('models_imported_successfully', 0)}",
            f"  Created Without Build: {manifest['summary'].get('models_created_without_build', 0)}",
            f"  Imported with Fallback Runtime: {manifest['summary'].get('models_imported_with_fallback', 0)}",
            "",
            "Jobs:",
            f"  Total Jobs: {manifest['summary'].get('total_jobs', 0)}",
            f"  Imported Successfully: {manifest['summary'].get('jobs_imported_successfully', 0)}",
            f"  Created with Fallback Runtime: {manifest['summary'].get('jobs_created_with_fallback', 0)}",
            f"  Skipped: {manifest['summary'].get('jobs_skipped', 0)}",
            "",
        ]
        
        # Applications imported with modifications
        if manifest.get("imported_with_modifications"):
            report_lines.extend([
                "-"*80,
                "",
                "APPLICATIONS REQUIRING MANUAL UPDATES",
                "",
                "The following applications were imported successfully but require manual",
                "script path updates:",
                "",
            ])
            
            for app in manifest["imported_with_modifications"]:
                report_lines.extend([
                    f"Application: {app['name']}",
                    "",
                    f"  Runtime: {app['runtime']}",
                    f"  Current Script: {app['current_script']}",
                    f"  Required Script: {app['original_script']}",
                    f"  Reason: {app['reason']}",
                    "",
                    "  Action Required:",
                    f"  1. Go to CML UI -> Projects -> {manifest['target_project']} -> Applications",
                    f"  2. Select application: {app['name']}",
                    "  3. Click Settings",
                    f"  4. Update Script field from '{app['current_script']}' to '{app['original_script']}'",
                    "  5. Save and start the application",
                    "",
                ])
        
        # Applications removed from manifest
        if manifest.get("removed_from_manifest"):
            report_lines.extend([
                "-"*80,
                "",
                "APPLICATIONS NOT IMPORTED",
                "",
                "The following applications could not be imported and require manual recreation:",
                "",
            ])
            
            for app in manifest["removed_from_manifest"]:
                report_lines.extend([
                    f"Application: {app['name']}",
                    "",
                    f"  Runtime: {app.get('runtime', 'N/A')}",
                    f"  Script: {app.get('script', 'N/A')}",
                    f"  Reason: {app['reason']}",
                    f"  Action: {app['action']}",
                    "",
                ])
        
        # Applications skipped
        if manifest.get("skipped_applications"):
            report_lines.extend([
                "-"*80,
                "",
                "APPLICATIONS SKIPPED",
                "",
                "The following applications were skipped during import:",
                "",
            ])
            
            for app in manifest["skipped_applications"]:
                report_lines.extend([
                    f"Application: {app['name']}",
                    "",
                    f"  Required Runtime: {app.get('runtime', 'N/A')}",
                    f"  Script: {app.get('script', 'N/A')}",
                    f"  Reason: {app['reason']}",
                    f"  Action: {app['action']}",
                    "",
                ])
        
        # Applications imported with fallback
        if manifest.get("imported_with_fallback"):
            report_lines.extend([
                "-"*80,
                "",
                "APPLICATIONS USING FALLBACK RUNTIME",
                "",
                "The following applications were imported with a fallback runtime:",
                "",
            ])
            
            for app in manifest["imported_with_fallback"]:
                report_lines.extend([
                    f"Application: {app['name']}",
                    "",
                    f"  Required Runtime: {app.get('required_runtime', 'N/A')}",
                    f"  Fallback Runtime: {app.get('fallback_runtime', 'N/A')}",
                    f"  Script: {app.get('script', 'N/A')}",
                    f"  Action: {app.get('action', 'Test functionality')}",
                    "",
                ])
        
        # Models created without build
        if manifest.get("models_created_without_build"):
            report_lines.extend([
                "-"*80,
                "",
                "MODELS CREATED WITHOUT BUILD",
                "",
                "The following models were created but builds failed. Manual rebuild required:",
                "",
            ])
            
            for model in manifest["models_created_without_build"]:
                report_lines.extend([
                    f"Model: {model['name']}",
                    "",
                    f"  Runtime: {model.get('runtime', 'N/A')}",
                    f"  Reason: {model['reason']}",
                    f"  Action: {model['action']}",
                    "",
                    "  Steps to Rebuild:",
                    f"  1. Go to CML UI -> Projects -> {manifest['target_project']} -> Models",
                    f"  2. Select model: {model['name']}",
                    "  3. Click 'New Build'",
                    "  4. Select appropriate runtime and build",
                    "",
                ])
        
        # Models imported with fallback
        if manifest.get("models_imported_with_fallback"):
            report_lines.extend([
                "-"*80,
                "",
                "MODELS USING FALLBACK RUNTIME",
                "",
                "The following models were imported with a fallback runtime:",
                "",
            ])
            
            for model in manifest["models_imported_with_fallback"]:
                report_lines.extend([
                    f"Model: {model['name']}",
                    "",
                    f"  Required Runtime: {model.get('required_runtime', 'N/A')}",
                    f"  Fallback Runtime: {model.get('fallback_runtime', 'N/A')}",
                    f"  Action: {model.get('action', 'Test functionality')}",
                    "",
                ])
        
        # Jobs created with fallback
        if manifest.get("jobs_created_with_fallback"):
            report_lines.extend([
                "-"*80,
                "",
                "JOBS USING FALLBACK RUNTIME",
                "",
                "The following jobs were created with a fallback runtime:",
                "",
            ])
            
            for job in manifest["jobs_created_with_fallback"]:
                report_lines.extend([
                    f"Job: {job['name']}",
                    "",
                    f"  Required Runtime: {job.get('required_runtime', 'N/A')}",
                    f"  Fallback Runtime: {job.get('fallback_runtime', 'N/A')}",
                    f"  Action: {job.get('action', 'Test functionality')}",
                    "",
                ])
        
        # Jobs skipped
        if manifest.get("jobs_skipped"):
            report_lines.extend([
                "-"*80,
                "",
                "JOBS SKIPPED",
                "",
                "The following jobs were skipped during import:",
                "",
            ])
            
            for job in manifest["jobs_skipped"]:
                report_lines.extend([
                    f"Job: {job['name']}",
                    "",
                    f"  Runtime: {job.get('runtime', 'N/A')}",
                    f"  Reason: {job['reason']}",
                    f"  Action: {job['action']}",
                    "",
                    "  Steps to Recreate:",
                    f"  1. Go to CML UI -> Projects -> {manifest['target_project']} -> Jobs",
                    "  2. Click 'New Job'",
                    f"  3. Set name: {job['name']}",
                    "  4. Configure job with appropriate runtime and settings",
                    "  5. Save",
                    "",
                ])
        
        # Recommendations
        if manifest.get("recommendations"):
            report_lines.extend([
                "-"*80,
                "",
                "RECOMMENDATIONS",
                "",
            ])
            for rec in manifest["recommendations"]:
                report_lines.append(f"  - {rec}")
            report_lines.append("")
        
        # Footer
        report_lines.extend([
            "-"*80,
            "",
            "ADDITIONAL RESOURCES",
            "",
            "  - JSON Manifest: manual-steps-required.json (for automation)",
            "  - Migration Logs: Check the logs directory for detailed migration output",
            "",
            "="*80,
            "",
            f"Report generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "="*80,
        ])
        
        # Write to file
        try:
            with open(report_path, 'w') as f:
                f.write('\n'.join(report_lines))
            logging.info(f"Generated human-readable report: {report_path}")
        except Exception as e:
            logging.warning(f"Failed to generate human-readable report: {e}")
    
    def _generate_manual_steps_manifest(self):
        """Generate a manifest of applications and models that need manual attention"""
        from datetime import datetime
        
        # Check if there are any applications needing attention
        apps_needing_attention = (
            len(self.import_tracking["apps_removed_from_manifest"]) +
            len(self.import_tracking["apps_skipped"]) +
            len(self.import_tracking["apps_imported_with_fallback"]) +
            len(self.import_tracking.get("apps_imported_with_modifications", []))
        )
        
        # Check if there are any models needing attention
        models_needing_attention = (
            len(self.import_tracking.get("models_created_without_build", [])) +
            len(self.import_tracking.get("models_imported_with_fallback", []))
        )
        
        # Check if there are any jobs needing attention
        jobs_needing_attention = (
            len(self.import_tracking.get("jobs_created_with_fallback", [])) +
            len(self.import_tracking.get("jobs_skipped", []))
        )
        
        total_needing_attention = apps_needing_attention + models_needing_attention + jobs_needing_attention
        
        if total_needing_attention == 0:
            logging.info("✅ All applications, models, and jobs imported successfully, no manual steps required")
            return
        
        # Create manifest
        manifest = {
            "migration_date": datetime.now().isoformat(),
            "source_project": "source",  # Will be filled by caller if needed
            "target_project": self.project_name,
            "summary": {
                "total_applications": (
                    len(self.import_tracking["apps_imported_successfully"]) + apps_needing_attention
                ),
                "apps_imported_successfully": len(self.import_tracking["apps_imported_successfully"]),
                "apps_imported_with_modifications": len(self.import_tracking.get("apps_imported_with_modifications", [])),
                "apps_imported_with_fallback": len(self.import_tracking["apps_imported_with_fallback"]),
                "apps_removed_from_manifest": len(self.import_tracking["apps_removed_from_manifest"]),
                "apps_skipped": len(self.import_tracking["apps_skipped"]),
                "total_models": (
                    len(self.import_tracking.get("models_imported_successfully", [])) + models_needing_attention
                ),
                "models_imported_successfully": len(self.import_tracking.get("models_imported_successfully", [])),
                "models_created_without_build": len(self.import_tracking.get("models_created_without_build", [])),
                "models_imported_with_fallback": len(self.import_tracking.get("models_imported_with_fallback", [])),
                "total_jobs": (
                    len(self.import_tracking.get("jobs_imported_successfully", [])) + jobs_needing_attention
                ),
                "jobs_imported_successfully": len(self.import_tracking.get("jobs_imported_successfully", [])),
                "jobs_created_with_fallback": len(self.import_tracking.get("jobs_created_with_fallback", [])),
                "jobs_skipped": len(self.import_tracking.get("jobs_skipped", []))
            },
            "imported_with_modifications": self.import_tracking.get("apps_imported_with_modifications", []),
            "removed_from_manifest": self.import_tracking["apps_removed_from_manifest"],
            "skipped_applications": self.import_tracking["apps_skipped"],
            "imported_with_fallback": self.import_tracking["apps_imported_with_fallback"],
            "models_created_without_build": self.import_tracking.get("models_created_without_build", []),
            "models_imported_with_fallback": self.import_tracking.get("models_imported_with_fallback", []),
            "jobs_created_with_fallback": self.import_tracking.get("jobs_created_with_fallback", []),
            "jobs_skipped": self.import_tracking.get("jobs_skipped", []),
            "recommendations": [
                "Review applications imported with modifications and update script paths",
                "Test applications imported with fallback runtimes",
                "Manually recreate applications that were removed",
                "Rebuild models that were created without builds",
                "Test models imported with fallback runtimes",
                "Test jobs imported with fallback runtimes",
                "Manually recreate jobs that were skipped",
                "Install missing runtimes if available"
            ]
        }
        
        # Save to file
        import os
        manifest_path = os.path.join(self.top_level_dir, self.project_name, "manual-steps-required.json")
        os.makedirs(os.path.dirname(manifest_path), exist_ok=True)
        
        write_json_file(file_path=manifest_path, json_data=manifest)
        
        # Also generate human-readable report
        report_path = os.path.join(self.top_level_dir, self.project_name, "MIGRATION_REPORT.txt")
        self._generate_human_readable_report(manifest, report_path)
        
        logging.info(f"\n📋 Manual Steps Required:")
        logging.info(f"  Applications:")
        logging.info(f"    • Imported with modifications: {manifest['summary']['apps_imported_with_modifications']}")
        logging.info(f"    • Removed from manifest: {manifest['summary']['apps_removed_from_manifest']}")
        logging.info(f"    • Skipped: {manifest['summary']['apps_skipped']}")
        logging.info(f"    • Imported with fallback: {manifest['summary']['apps_imported_with_fallback']}")
        logging.info(f"  Models:")
        logging.info(f"    • Created without build: {manifest['summary']['models_created_without_build']}")
        logging.info(f"    • Imported with fallback: {manifest['summary']['models_imported_with_fallback']}")
        logging.info(f"  Jobs:")
        logging.info(f"    • Created with fallback: {manifest['summary']['jobs_created_with_fallback']}")
        logging.info(f"    • Skipped: {manifest['summary']['jobs_skipped']}")
        logging.info(f"  📁 JSON manifest: {manifest_path}")
        logging.info(f"  📄 Human-readable report: {report_path}")

    def collect_imported_project_data(self, project_id: str):
        proj_data_raw = self.get_project_infov2(proj_id=project_id)
        proj_info_flatten = flatten_json_data(proj_data_raw)
        proj_data = [extract_fields(proj_info_flatten, constants.PROJECT_MAPV2)]
        proj_list = [
            self.project_name.lower()
            if self.check_project_exist(self.project_name)
            else None
        ]
        model_data, model_list = self.collect_import_model_list(project_id=project_id)
        app_data, app_list = self.collect_import_application_list(project_id=project_id)
        job_data, job_list = self.collect_import_job_list(project_id=project_id)
        return (
            proj_data,
            proj_list,
            model_data,
            model_list,
            app_data,
            app_list,
            job_data,
            job_list,
        )

    def create_models(self, project_id: str, models_metadata_filepath: str):
        try:
            verbose = os.environ.get('CMLUTILS_VERBOSE', 'False').lower() == 'true'
            if verbose:
                logging.debug("Starting model creation process for project_id: %s", project_id)
                logging.debug("Reading models metadata from: %s", models_metadata_filepath)
            
            runtime_list = self.get_all_runtimes()
            proj_with_runtime = is_project_configured_with_runtimes(
                host=self.host,
                username=self.username,
                project_name=self.project_name,
                api_key=self.api_key,
                ca_path=self.ca_path,
                project_slug=self.project_slug,
            )
            
            if verbose:
                logging.debug("Project configured with runtimes: %s", proj_with_runtime)
            
            # Initialize model tracking
            if "models_imported_successfully" not in self.import_tracking:
                self.import_tracking["models_imported_successfully"] = []
            if "models_created_without_build" not in self.import_tracking:
                self.import_tracking["models_created_without_build"] = []
            if "models_imported_with_fallback" not in self.import_tracking:
                self.import_tracking["models_imported_with_fallback"] = []
            
            model_metadata_list = read_json_file(models_metadata_filepath)
            if model_metadata_list != None:
                if verbose:
                    logging.debug("Found %d models to import", len(model_metadata_list))
                
                for model_metadata in model_metadata_list:
                    model_name = model_metadata.get("name", "unknown")
                    
                    if not self.check_model_exist(
                        model_name=model_metadata["name"], proj_id=project_id
                    ):
                        model_metadata["project_id"] = project_id
                        required_runtime = model_metadata.get("runtime_identifier", None)
                        runtime_available = False
                        used_fallback = False
                        
                        # Check if required runtime exists in target
                        if required_runtime and proj_with_runtime:
                            runtime_available = any(
                                r.get("image_identifier") == required_runtime
                                for r in runtime_list.get("runtimes", [])
                            )
                            
                            if not runtime_available:
                                logging.warning(
                                    f"⚠️  Model '{model_name}' requires runtime '{required_runtime}' which is not available"
                                )
                                # Try to find fallback runtime
                                if all(k in model_metadata for k in ["runtime_edition", "runtime_editor", "runtime_kernel"]):
                                    fallback_runtime = get_best_runtime(
                                        runtime_list["runtimes"],
                                        model_metadata["runtime_edition"],
                                        model_metadata["runtime_editor"],
                                        model_metadata["runtime_kernel"],
                                        model_metadata.get("runtime_shortversion", ""),
                                        model_metadata.get("runtime_fullversion", ""),
                                    )
                                    if fallback_runtime:
                                        logging.info(f"Using fallback runtime for model '{model_name}': {fallback_runtime}")
                                        model_metadata["runtime_identifier"] = fallback_runtime
                                        used_fallback = True
                                        runtime_available = True
                        
                        if (
                            not "runtime_identifier" in model_metadata
                            and proj_with_runtime
                        ):
                            runtime_identifier = get_best_runtime(
                                runtime_list["runtimes"],
                                model_metadata["runtime_edition"],
                                model_metadata["runtime_editor"],
                                model_metadata["runtime_kernel"],
                                model_metadata["runtime_shortversion"],
                                model_metadata["runtime_fullversion"],
                            )
                            if runtime_identifier != None:
                                model_metadata[
                                    "runtime_identifier"
                                ] = runtime_identifier
                            else:
                                logging.warning(
                                    "Couldn't locate runtime identifier for model %s",
                                    model_metadata["name"],
                                )
                                # Try first available runtime
                                if runtime_list.get("runtimes"):
                                    first_runtime = runtime_list["runtimes"][0].get("image_identifier")
                                    if first_runtime:
                                        logging.info(f"Using first available runtime for model '{model_name}': {first_runtime}")
                                        model_metadata["runtime_identifier"] = first_runtime
                                        used_fallback = True
                                    else:
                                        logging.warning(f"No runtimes available, skipping build for model '{model_name}'")
                                        model_metadata["runtime_identifier"] = None
                        
                        if verbose:
                            logging.debug("Creating model: %s", model_metadata["name"])
                        
                        try:
                            model_id = self.create_model_v2(
                                proj_id=project_id, model_metadata=model_metadata
                            )
                            
                            if verbose:
                                logging.debug("Created model with ID: %s, attempting build...", model_id)
                            
                            # Try to create build, but don't crash if it fails
                            build_created = False
                            if model_metadata.get("runtime_identifier"):
                                try:
                                    self.create_model_build_v2(
                                        proj_id=project_id,
                                        model_id=model_id,
                                        model_metadata=model_metadata,
                                    )
                                    build_created = True
                                    
                                    if used_fallback:
                                        logging.info(f"✅ Model '{model_name}' created with fallback runtime")
                                        self.import_tracking["models_imported_with_fallback"].append({
                                            "name": model_name,
                                            "required_runtime": required_runtime,
                                            "fallback_runtime": model_metadata["runtime_identifier"],
                                            "action": "Verify model functionality with the fallback runtime"
                                        })
                                    else:
                                        logging.info(f"✅ Model '{model_name}' migrated successfully")
                                        self.import_tracking["models_imported_successfully"].append({
                                            "name": model_name,
                                            "runtime": model_metadata.get("runtime_identifier", "default")
                                        })
                                
                                except HTTPError as e:
                                    error_message = str(e)
                                    if hasattr(e, 'response') and e.response is not None:
                                        try:
                                            error_json = e.response.json()
                                            error_message = error_json.get("message") or error_json.get("error") or str(e)
                                        except:
                                            pass
                                    
                                    logging.warning(f"⚠️  Failed to create build for model '{model_name}': {error_message}")
                                    logging.info(f"Model '{model_name}' created but without build - manual intervention required")
                                    self.import_tracking["models_created_without_build"].append({
                                        "name": model_name,
                                        "runtime": required_runtime or "unknown",
                                        "reason": f"Build creation failed: {error_message}",
                                        "action": "Manually rebuild the model in CML UI with an appropriate runtime"
                                    })
                            else:
                                logging.info(f"⚠️  Model '{model_name}' created without build (no runtime available)")
                                self.import_tracking["models_created_without_build"].append({
                                    "name": model_name,
                                    "runtime": required_runtime or "unknown",
                                    "reason": "No suitable runtime available in target workspace",
                                    "action": "Manually rebuild the model in CML UI after adding the required runtime"
                                })
                        
                        except HTTPError as e:
                            error_message = str(e)
                            if hasattr(e, 'response') and e.response is not None:
                                try:
                                    error_json = e.response.json()
                                    error_message = error_json.get("message") or error_json.get("error") or str(e)
                                except:
                                    pass
                            
                            logging.error(f"Failed to create model '{model_name}': {error_message}")
                            self.import_tracking["models_created_without_build"].append({
                                "name": model_name,
                                "runtime": required_runtime or "unknown",
                                "reason": f"Model creation failed: {error_message}",
                                "action": "Manually recreate the model in CML UI"
                            })
                            continue
                    else:
                        logging.info(
                            "Skipping the already existing model- %s",
                            model_metadata["name"],
                        )

            return
        except FileNotFoundError as e:
            logging.info("No model-metadata file found for migration")
            return
        except Exception as e:
            logging.error("Model migration failed")
            logging.error(f"Error: {e}")
            # Don't raise - log the error and continue with jobs
            logging.info("Continuing with remaining imports despite model errors...")
            return

    def create_stoppped_applications(self, project_id: str, app_metadata_filepath: str):
        try:
            runtime_list = self.get_all_runtimes()
            proj_with_runtime = is_project_configured_with_runtimes(
                host=self.host,
                username=self.username,
                project_name=self.project_name,
                api_key=self.api_key,
                ca_path=self.ca_path,
                project_slug=self.project_slug,
            )
            app_metadata_list = read_json_file(app_metadata_filepath)
            if app_metadata_list != None:
                for app_metadata in app_metadata_list:
                    if not self.check_app_exist(
                        subdomain=app_metadata["subdomain"], proj_id=project_id
                    ):
                        app_metadata["project_id"] = project_id
                        
                        # Check if all required runtime fields are present
                        has_runtime_fields = all(
                            field in app_metadata
                            for field in [
                                "runtime_edition",
                                "runtime_editor",
                                "runtime_kernel",
                                "runtime_shortversion",
                                "runtime_fullversion",
                            ]
                        )
                        
                        # For projects using runtimes, only set runtime_identifier if not already present from export
                        if proj_with_runtime and not "runtime_identifier" in app_metadata:
                            if has_runtime_fields:
                                runtime_identifier = get_best_runtime(
                                    runtime_list["runtimes"],
                                    app_metadata["runtime_edition"],
                                    app_metadata["runtime_editor"],
                                    app_metadata["runtime_kernel"],
                                    app_metadata["runtime_shortversion"],
                                    app_metadata["runtime_fullversion"],
                                )
                                if runtime_identifier != None:
                                    app_metadata["runtime_identifier"] = runtime_identifier
                                    logging.info(
                                        f"Set runtime_identifier from runtime fields for app {app_metadata.get('name')}"
                                    )
                                else:
                                    # Try first available runtime if no match found
                                    if runtime_list and "runtimes" in runtime_list and runtime_list["runtimes"]:
                                        first_runtime = runtime_list["runtimes"][0]
                                        # V2 API returns snake_case fields
                                        app_metadata["runtime_identifier"] = (
                                            first_runtime.get("image_identifier") or first_runtime.get("full_version")
                                        )
                                        logging.info(
                                            f"Using first available runtime for app {app_metadata.get('name')}: {app_metadata['runtime_identifier']}"
                                        )
                            else:
                                # If runtime fields are missing, use first available runtime from workspace
                                if runtime_list and "runtimes" in runtime_list and runtime_list["runtimes"]:
                                    first_runtime = runtime_list["runtimes"][0]
                                    # Use the first available runtime - V2 API returns snake_case fields
                                    app_metadata["runtime_identifier"] = (
                                        first_runtime.get("image_identifier") or first_runtime.get("full_version")
                                    )
                                    logging.info(
                                        f"Using first available runtime for app {app_metadata.get('name')}"
                                    )
                        # Parse environment from JSON string to dict if needed for V2 API
                        if "environment" in app_metadata and isinstance(
                            app_metadata["environment"], str
                        ):
                            try:
                                app_metadata["environment"] = json.loads(
                                    app_metadata["environment"]
                                )
                            except json.JSONDecodeError:
                                logging.warning(
                                    f"Could not parse environment JSON for app {app_metadata.get('name', 'unknown')}, using empty dict"
                                )
                                app_metadata["environment"] = {}
                        
                        # Check runtime availability and decide import strategy
                        app_name = app_metadata.get("name", "unknown")
                        script_path = app_metadata.get("script", "")
                        required_runtime = app_metadata.get("runtime_identifier")
                        
                        is_system_script = script_path and any(
                            script_path.startswith(p) for p in ["/opt/", "/usr/", "/bin/", "/etc/"]
                        )
                        
                        # Check if required runtime exists in target workspace
                        runtime_available = False
                        if required_runtime:
                            available_runtime_ids = [r.get("image_identifier") for r in runtime_list.get("runtimes", [])]
                            runtime_available = required_runtime in available_runtime_ids
                            logging.info(
                                f"Application '{app_name}' requires runtime: {required_runtime} "
                                f"({'available' if runtime_available else 'NOT available'} in target)"
                            )
                        
                        # Decision logic based on runtime availability and script type
                        if not required_runtime or runtime_available:
                            # Runtime available (or not specified), attempt import
                            
                            # Convert absolute system script paths to relative paths
                            # (placeholder files are created at relative paths during export)
                            converted_script = False
                            original_script_path = script_path
                            if script_path and script_path.startswith("/"):
                                relative_script_path = script_path.lstrip("/")
                                app_metadata["script"] = relative_script_path
                                converted_script = True
                                logging.info(
                                    f"Converting system script path for '{app_name}': "
                                    f"{original_script_path} → {relative_script_path}"
                                )
                            
                            try:
                                app_id = self.create_application_v2(
                                    proj_id=project_id, app_metadata=app_metadata
                                )
                                self.stop_application_v2(proj_id=project_id, app_id=app_id)
                                
                                if converted_script:
                                    logging.info(
                                        f"✅ Application '{app_name}' imported with converted script path. "
                                        f"Update in CML UI to: {original_script_path}"
                                    )
                                    # Track as needing manual update
                                    if "apps_imported_with_modifications" not in self.import_tracking:
                                        self.import_tracking["apps_imported_with_modifications"] = []
                                    self.import_tracking["apps_imported_with_modifications"].append({
                                        "name": app_name,
                                        "runtime": required_runtime,
                                        "original_script": original_script_path,
                                        "current_script": app_metadata["script"],
                                        "reason": "System script path converted to relative path for migration",
                                        "action": f"Update application script in CML UI from '{app_metadata['script']}' back to '{original_script_path}'"
                                    })
                                else:
                                    logging.info(f"✅ Application '{app_name}' imported successfully")
                                    self.import_tracking["apps_imported_successfully"].append({
                                        "name": app_name,
                                        "runtime": required_runtime or "default",
                                        "script": script_path
                                    })
                            except HTTPError as e:
                                # Application creation failed
                                logging.error(f"Failed to import application '{app_name}': {e}")
                                error_message = str(e)
                                if hasattr(e, 'response') and e.response is not None:
                                    try:
                                        error_json = e.response.json()
                                        error_message = error_json.get("message") or error_json.get("error") or str(e)
                                    except:
                                        pass
                                
                                self.import_tracking["apps_removed_from_manifest"].append({
                                    "name": app_name,
                                    "runtime": required_runtime,
                                    "script": script_path,
                                    "reason": f"Failed to create application: {error_message}",
                                    "action": "Check application configuration and manually recreate if needed"
                                })
                                continue
                        
                        else:
                            # Runtime NOT available
                            if is_system_script:
                                # System script needs its specific runtime
                                logging.warning(
                                    f"⏭️  Skipped application '{app_name}': "
                                    f"Required runtime not available"
                                )
                                self.import_tracking["apps_skipped"].append({
                                    "name": app_name,
                                    "runtime": required_runtime,
                                    "script": script_path,
                                    "reason": "Required runtime not available",
                                    "action": "Install required runtime or manually recreate application"
                                })
                                continue
                            else:
                                # Project script, try with fallback runtime
                                try:
                                    app_metadata_fallback = app_metadata.copy()
                                    # Use first available runtime as fallback
                                    if runtime_list and "runtimes" in runtime_list and runtime_list["runtimes"]:
                                        fallback_runtime = runtime_list["runtimes"][0].get("image_identifier")
                                        app_metadata_fallback["runtime_identifier"] = fallback_runtime
                                        
                                        app_id = self.create_application_v2(
                                            proj_id=project_id, app_metadata=app_metadata_fallback
                                        )
                                        self.stop_application_v2(proj_id=project_id, app_id=app_id)
                                        logging.warning(
                                            f"⚠️  Application '{app_name}' imported with fallback runtime. "
                                            f"Please test functionality."
                                        )
                                        self.import_tracking["apps_imported_with_fallback"].append({
                                            "name": app_name,
                                            "required_runtime": required_runtime,
                                            "fallback_runtime": fallback_runtime,
                                            "script": script_path,
                                            "action": "Test functionality, may need runtime installation"
                                        })
                                except HTTPError as e:
                                    # Even fallback failed
                                    logging.error(f"❌ Failed to import '{app_name}' even with fallback runtime")
                                    self.import_tracking["apps_skipped"].append({
                                        "name": app_name,
                                        "runtime": required_runtime,
                                        "script": script_path,
                                        "reason": "Failed even with fallback runtime",
                                        "action": "Manually recreate application"
                                    })
                                    continue
                    else:
                        logging.info(
                            "Skipping the already existing application %s with same subdomain- %s",
                            app_metadata["name"],
                            app_metadata["subdomain"],
                        )

            return
        except FileNotFoundError as e:
            logging.info("No application-metadata file found for migration")
            return
        except Exception as e:
            logging.error("Application migration failed")
            logging.error(f"Error: {e}")
            raise

    def create_paused_jobs(self, project_id: str, job_metadata_filepath: str):
        try:
            runtime_list = self.get_all_runtimes()
            spark_runtime_id = self.get_spark_runtimeaddons()
            proj_with_runtime = is_project_configured_with_runtimes(
                host=self.host,
                username=self.username,
                project_name=self.project_name,
                api_key=self.api_key,
                ca_path=self.ca_path,
                project_slug=self.project_slug,
            )
            
            # Initialize job tracking
            if "jobs_imported_successfully" not in self.import_tracking:
                self.import_tracking["jobs_imported_successfully"] = []
            if "jobs_created_with_fallback" not in self.import_tracking:
                self.import_tracking["jobs_created_with_fallback"] = []
            if "jobs_skipped" not in self.import_tracking:
                self.import_tracking["jobs_skipped"] = []
            
            job_metadata_list = read_json_file(job_metadata_filepath)
            src_tgt_job_mapping = {}
            # Create job in target CML workspace.
            if job_metadata_list != None:
                for job_metadata in job_metadata_list:
                    job_name = job_metadata.get("name", "unknown")
                    target_job_id = self.check_job_exist(
                        job_name=job_metadata["name"],
                        script=job_metadata["script"],
                        proj_id=project_id,
                    )
                    if target_job_id == None:
                        job_metadata["project_id"] = project_id
                        job_metadata["paused"] = True
                        required_runtime = job_metadata.get("runtime_identifier", None)
                        runtime_available = False
                        used_fallback = False
                        
                        # Check if required runtime exists in target
                        if required_runtime and proj_with_runtime:
                            runtime_available = any(
                                r.get("image_identifier") == required_runtime
                                for r in runtime_list.get("runtimes", [])
                            )
                            
                            if not runtime_available:
                                logging.warning(
                                    f"⚠️  Job '{job_name}' requires runtime '{required_runtime}' which is not available"
                                )
                                # Try to find fallback runtime
                                if all(k in job_metadata for k in ["runtime_edition", "runtime_editor", "runtime_kernel"]):
                                    fallback_runtime = get_best_runtime(
                                        runtime_list["runtimes"],
                                        job_metadata["runtime_edition"],
                                        job_metadata["runtime_editor"],
                                        job_metadata["runtime_kernel"],
                                        job_metadata.get("runtime_shortversion", ""),
                                        job_metadata.get("runtime_fullversion", ""),
                                    )
                                    if fallback_runtime:
                                        logging.info(f"Using fallback runtime for job '{job_name}': {fallback_runtime}")
                                        job_metadata["runtime_identifier"] = fallback_runtime
                                        used_fallback = True
                                        runtime_available = True
                        
                        if spark_runtime_id != None:
                            job_metadata["runtime_addon_identifiers"] = [
                                spark_runtime_id
                            ]
                        if (
                            not "runtime_identifier" in job_metadata
                            and proj_with_runtime
                        ):
                            runtime_identifier = get_best_runtime(
                                runtime_list["runtimes"],
                                job_metadata["runtime_edition"],
                                job_metadata["runtime_editor"],
                                job_metadata["runtime_kernel"],
                                job_metadata["runtime_shortversion"],
                                job_metadata["runtime_fullversion"],
                            )
                            if runtime_identifier != None:
                                job_metadata["runtime_identifier"] = runtime_identifier
                            else:
                                # Try first available runtime
                                if runtime_list.get("runtimes"):
                                    first_runtime = runtime_list["runtimes"][0].get("image_identifier")
                                    if first_runtime:
                                        logging.info(f"Using first available runtime for job '{job_name}': {first_runtime}")
                                        job_metadata["runtime_identifier"] = first_runtime
                                        used_fallback = True
                        
                        # Fix environment field - API expects JSON object, not string
                        if "environment" in job_metadata and isinstance(job_metadata["environment"], str):
                            try:
                                job_metadata["environment"] = json.loads(job_metadata["environment"])
                            except json.JSONDecodeError:
                                logging.warning(f"Could not parse environment for job {job_metadata['name']}, setting to empty dict")
                                job_metadata["environment"] = {}
                        
                        try:
                            target_job_id = self.create_job_v2(
                                proj_id=project_id, job_metadata=job_metadata
                            )
                            
                            if used_fallback:
                                logging.info(f"✅ Job '{job_name}' created with fallback runtime")
                                self.import_tracking["jobs_created_with_fallback"].append({
                                    "name": job_name,
                                    "required_runtime": required_runtime,
                                    "fallback_runtime": job_metadata.get("runtime_identifier"),
                                    "action": "Verify job functionality with the fallback runtime"
                                })
                            else:
                                logging.info(f"✅ Job '{job_name}' migrated successfully")
                                self.import_tracking["jobs_imported_successfully"].append({
                                    "name": job_name,
                                    "runtime": job_metadata.get("runtime_identifier", "default")
                                })
                        
                        except HTTPError as e:
                            error_message = str(e)
                            if hasattr(e, 'response') and e.response is not None:
                                try:
                                    error_json = e.response.json()
                                    error_message = error_json.get("message") or error_json.get("error") or str(e)
                                except:
                                    pass
                            
                            logging.error(f"Failed to create job '{job_name}': {error_message}")
                            self.import_tracking["jobs_skipped"].append({
                                "name": job_name,
                                "runtime": required_runtime or "unknown",
                                "reason": f"Job creation failed: {error_message}",
                                "action": "Manually recreate the job in CML UI"
                            })
                            target_job_id = None
                            continue
                    else:
                        logging.info(
                            "Skipping the already existing job- %s",
                            job_metadata["name"],
                        )

                    if target_job_id:
                        src_tgt_job_mapping[job_metadata["source_jobid"]] = target_job_id

                # Update job dependency
                for job_metadata in job_metadata_list:
                    if "parent_jobid" in job_metadata:
                        tgt_job_id = src_tgt_job_mapping[job_metadata["source_jobid"]]
                        tgt_parent_jobid = src_tgt_job_mapping[
                            job_metadata["parent_jobid"]
                        ]
                        json_post_req = {"parent_id": tgt_parent_jobid}
                        self.update_job_v2(
                            proj_id=project_id,
                            job_id=tgt_job_id,
                            job_metadata=json_post_req,
                        )
            logging.warning("Internal job report recipients may not get migrated")

            return
        except FileNotFoundError as e:
            logging.info("No job-metadata file found for migration")
            return
        except Exception as e:
            logging.error("Job migration failed")
            logging.error(f"Error: {e}")
            # Don't raise - log the error and continue
            logging.info("Continuing despite job errors...")
            return

    def get_project_infov2(self, proj_id: str):
        endpoint = Template(ApiV2Endpoints.GET_PROJECT.value).substitute(
            project_id=proj_id
        )
        response = call_api_v2(
            host=self.host,
            endpoint=endpoint,
            method="GET",
            user_token=self.apiv2_key,
            ca_path=self.ca_path,
        )
        return response.json()

    def collect_import_job_list(self, project_id):
        job_list = self.get_jobs_listv2(proj_id=project_id)["jobs"]
        job_name_list = []
        if len(job_list) == 0:
            logging.info("Jobs are not present in the project %s.", self.project_name)
        else:
            logging.info("Project {} has {} Jobs".format(self.project_name, len(job_list)))
        job_metadata_list = []
        for job in job_list:
            job_info_flatten = flatten_json_data(job)
            job_metadata = extract_fields(job_info_flatten, constants.JOB_MAP)
            job_name_list.append(job_metadata["name"])
            job_metadata_list.append(job_metadata)
        self.metrics_data["total_job"] = len(job_name_list)
        self.metrics_data["job_name_list"] = sorted(job_name_list)
        return job_metadata_list, sorted(job_name_list)

    def collect_import_model_list(self, project_id):
        model_list = self.get_models_listv2(proj_id=project_id)["models"]
        model_name_list = []
        if len(model_list) == 0:
            logging.info("Models are not present in the project %s.", self.project_name)
        else:
            logging.info("Project {} has {} Models".format(self.project_name, len(model_list)))
        model_metadata_list = []
        model_detail_data = {}
        for model in model_list:
            model_info_flatten = flatten_json_data(model)
            model_detail_data["name"] = model_info_flatten["name"]
            model_detail_data["description"] = model_info_flatten["description"]
            model_detail_data["disable_authentication"] = model_info_flatten["auth_enabled"] if isinstance(model_info_flatten["auth_enabled"], bool) else model_info_flatten["auth_enabled"]
            model_details = self.get_models_detailv2(
                proj_id=project_id, model_id=model_info_flatten["id"]
            )
            model_metadata = {}
            if len(model_details["model_builds"]) > 0:
                model_metadata = extract_fields(
                    model_details["model_builds"][0], constants.MODEL_MAPV2
                )
                model_detail_data.update(model_metadata)

            model_name_list.append(model_info_flatten["name"])
            model_metadata_list.append(model_detail_data)
        self.metrics_data["total_model"] = len(model_name_list)
        self.metrics_data["model_name_list"] = sorted(model_name_list)
        return model_metadata_list, sorted(model_name_list)

    def collect_import_application_list(self, project_id):
        app_list = self.get_application_listv2(proj_id=project_id)["applications"]
        app_name_list = []
        if len(app_list) == 0:
            logging.info(
                "Applications are not present in the project %s.", self.project_name
            )
        else:
            logging.info("Project {} has {} Application".format(self.project_name, len(app_list)))
        app_metadata_list = []
        for app in app_list:
            app_info_flatten = flatten_json_data(app)
            app_metadata = extract_fields(app_info_flatten, constants.APPLICATION_MAPV2)
            app_name_list.append(app_metadata["name"])
            app_metadata_list.append(app_metadata)
        self.metrics_data["total_application"] = len(app_name_list)
        self.metrics_data["application_name_list"] = sorted(app_name_list)
        return app_metadata_list, sorted(app_name_list)
