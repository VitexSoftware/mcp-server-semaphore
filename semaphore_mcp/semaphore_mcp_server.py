#!/usr/bin/env python3
"""
Semaphore MCP Server - Integration with Semaphore UI API using semaphore-client

This server provides access to Semaphore UI API functionality through
the Model Context Protocol (MCP), enabling AI assistants and other tools to
interact with Semaphore automation systems (Ansible, Terraform, etc.).

Author: Vítězslav Dvořák <info@vitexsoftware.cz>
License: MIT
"""

import os
import json
import logging
from typing import Any, Dict, List, Optional
from fastmcp import FastMCP
from dotenv import load_dotenv

import sys

# The semaphore_client package has internal imports that expect
# 'semaphore' to be importable as a top-level module. Add the
# package directory to sys.path to make this work.
import importlib.util
_spec = importlib.util.find_spec("semaphore_client")
if _spec and _spec.submodule_search_locations:
    for _loc in _spec.submodule_search_locations:
        if _loc not in sys.path:
            sys.path.insert(0, _loc)

from semaphore_client.api_client import ApiClient
from semaphore_client.configuration import Configuration
from semaphore_client.semaphore.project_api import ProjectApi
from semaphore_client.semaphore.task_api import TaskApi
from semaphore_client.semaphore.template_api import TemplateApi
from semaphore_client.semaphore.inventory_api import InventoryApi
from semaphore_client.semaphore.repository_api import RepositoryApi
from semaphore_client.semaphore.schedule_api import ScheduleApi
from semaphore_client.semaphore.user_api import UserApi
from semaphore_client.semaphore.key_store_api import KeyStoreApi
from semaphore_client.semaphore.variable_group_api import VariableGroupApi
from semaphore_client.semaphore.default_api import DefaultApi
from semaphore_client.models.project_request import ProjectRequest
from semaphore_client.models.template_request import TemplateRequest
from semaphore_client.models.inventory_request import InventoryRequest
from semaphore_client.models.repository_request import RepositoryRequest
from semaphore_client.models.schedule_request import ScheduleRequest
from semaphore_client.models.environment_request import EnvironmentRequest
from semaphore_client.models.project_project_id_tasks_post_request import (
    ProjectProjectIdTasksPostRequest,
)

# Load environment variables from .env file
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO if os.getenv("DEBUG") else logging.WARNING,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Initialize FastMCP
mcp = FastMCP("Semaphore MCP Server")

# MCP tool annotations (hints for clients / capability audits)
_RO_ANN = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": True,
}
_RW_ANN = {
    "readOnlyHint": False,
    "destructiveHint": False,
    "idempotentHint": False,
    "openWorldHint": True,
}
_DEL_ANN = {
    "readOnlyHint": False,
    "destructiveHint": True,
    "idempotentHint": True,
    "openWorldHint": True,
}

# Global API client
_api_client: Optional[ApiClient] = None


def get_api_client() -> ApiClient:
    """Get or create Semaphore API client with proper authentication.

    Returns:
        ApiClient: Authenticated Semaphore API client

    Raises:
        ValueError: If required environment variables are missing
    """
    global _api_client

    if _api_client is None:
        url = os.getenv("SEMAPHORE_URL")
        if not url:
            raise ValueError("SEMAPHORE_URL environment variable is required")

        token = os.getenv("SEMAPHORE_TOKEN")
        if not token:
            raise ValueError("SEMAPHORE_TOKEN environment variable is required")

        logger.info(f"Initializing Semaphore API client for {url}")

        config = Configuration(
            host=f"{url.rstrip('/')}/api",
            api_key={"bearer": token},
            api_key_prefix={"bearer": "Bearer"},
        )

        _api_client = ApiClient(config)
        logger.info("Successfully configured Semaphore API client")

    return _api_client


def is_read_only() -> bool:
    """Check if server is in read-only mode."""
    return os.getenv("READ_ONLY", "true").lower() in ("true", "1", "yes")


def validate_read_only() -> None:
    """Validate that write operations are allowed.

    Raises:
        ValueError: If server is in read-only mode
    """
    if is_read_only():
        raise ValueError(
            "Server is in read-only mode - write operations are not allowed. "
            "Set READ_ONLY=false to enable write operations."
        )


def format_response(data: Any) -> str:
    """Format response data as JSON string."""
    if hasattr(data, "to_dict"):
        return json.dumps(data.to_dict(), indent=2, default=str)
    if isinstance(data, list):
        return json.dumps(
            [item.to_dict() if hasattr(item, "to_dict") else item for item in data],
            indent=2,
            default=str,
        )
    return json.dumps(data, indent=2, default=str)


def _client_get(
    client: ApiClient,
    resource_path: str,
    path_params: Dict[str, Any],
    response_type: str,
) -> Any:
    """GET via ApiClient for endpoints missing from the generated API classes.

    python-semaphore-client 2.16.14 omits a few live Semaphore routes (notably
    schedule list and single-key GET). This helper fills those gaps without
    forking the generated client.
    """
    header_params: Dict[str, Optional[str]] = {"Accept": "application/json"}
    param = client.param_serialize(
        method="GET",
        resource_path=resource_path,
        path_params=path_params,
        query_params=[],
        header_params=header_params,
        body=None,
        post_params=[],
        files={},
        auth_settings=["bearer"],
        collection_formats={},
        _host=None,
        _request_auth=None,
    )
    response_data = client.call_api(*param)
    response_data.read()
    return client.response_deserialize(
        response_data=response_data,
        response_types_map={"200": response_type},
    ).data


# ============================================================================
# PROJECT MANAGEMENT
# ============================================================================


@mcp.tool(annotations=_RO_ANN)
def project_list() -> str:
    """List all projects accessible to the current user.

    Returns:
        JSON list of projects with their details.
    """
    client = get_api_client()
    api = ProjectApi(client)
    projects = api.projects_get()
    return format_response(projects)


@mcp.tool(annotations=_RO_ANN)
def project_get(project_id: int) -> str:
    """Get details of a specific project.

    Args:
        project_id: The ID of the project to retrieve.

    Returns:
        JSON object with project details.
    """
    client = get_api_client()
    api = ProjectApi(client)
    project = api.project_project_id_get(project_id=project_id)
    return format_response(project)


@mcp.tool(annotations=_RW_ANN)
def project_create(name: str, alert: bool = False, max_parallel_tasks: int = 0) -> str:
    """Create a new project.

    Args:
        name: Name of the project.
        alert: Whether to enable alerts for this project.
        max_parallel_tasks: Maximum number of parallel tasks (0 = unlimited).

    Returns:
        JSON object with the created project details.
    """
    validate_read_only()
    client = get_api_client()
    api = ProjectApi(client)
    request = ProjectRequest(
        name=name,
        alert=alert,
        max_parallel_tasks=max_parallel_tasks,
    )
    project = api.projects_post(project_request=request)
    return format_response(project)


@mcp.tool(annotations=_DEL_ANN)
def project_delete(project_id: int) -> str:
    """Delete a project.

    Args:
        project_id: The ID of the project to delete.

    Returns:
        Confirmation message.
    """
    validate_read_only()
    client = get_api_client()
    api = ProjectApi(client)
    api.project_project_id_delete(project_id=project_id)
    return json.dumps({"status": "deleted", "project_id": project_id})


# ============================================================================
# TASK MANAGEMENT
# ============================================================================


@mcp.tool(annotations=_RO_ANN)
def task_list(project_id: int) -> str:
    """List all tasks in a project.

    Args:
        project_id: The ID of the project.

    Returns:
        JSON list of tasks.
    """
    client = get_api_client()
    api = TaskApi(client)
    tasks = api.project_project_id_tasks_get(project_id=project_id)
    return format_response(tasks)


@mcp.tool(annotations=_RO_ANN)
def task_get(project_id: int, task_id: int) -> str:
    """Get details of a specific task.

    Args:
        project_id: The ID of the project.
        task_id: The ID of the task.

    Returns:
        JSON object with task details.
    """
    client = get_api_client()
    api = TaskApi(client)
    task = api.project_project_id_tasks_task_id_get(
        project_id=project_id, task_id=task_id
    )
    return format_response(task)


@mcp.tool(annotations=_RW_ANN)
def task_launch(
    project_id: int,
    template_id: int,
    debug: bool = False,
    dry_run: bool = False,
    diff: bool = False,
    environment: Optional[str] = None,
) -> str:
    """Launch a new task from a template.

    Args:
        project_id: The ID of the project.
        template_id: The ID of the template to run.
        debug: Enable debug mode for the task.
        dry_run: Perform a dry run (check mode).
        diff: Show diff output.
        environment: JSON string of extra environment variables.

    Returns:
        JSON object with the launched task details.
    """
    validate_read_only()
    client = get_api_client()
    api = TaskApi(client)
    request = ProjectProjectIdTasksPostRequest(
        template_id=template_id,
        debug=debug,
        dry_run=dry_run,
        diff=diff,
        environment=environment,
    )
    task = api.project_project_id_tasks_post(
        project_id=project_id,
        project_project_id_tasks_post_request=request,
    )
    return format_response(task)


@mcp.tool(annotations=_RW_ANN)
def task_stop(project_id: int, task_id: int) -> str:
    """Stop a running task.

    Args:
        project_id: The ID of the project.
        task_id: The ID of the task to stop.

    Returns:
        Confirmation message.
    """
    validate_read_only()
    client = get_api_client()
    api = TaskApi(client)
    api.project_project_id_tasks_task_id_stop_post(
        project_id=project_id, task_id=task_id
    )
    return json.dumps({"status": "stopped", "task_id": task_id})


@mcp.tool(annotations=_RO_ANN)
def task_output(project_id: int, task_id: int) -> str:
    """Get the output log of a task.

    Args:
        project_id: The ID of the project.
        task_id: The ID of the task.

    Returns:
        JSON list of task output lines.
    """
    client = get_api_client()
    api = TaskApi(client)
    output = api.project_project_id_tasks_task_id_output_get(
        project_id=project_id, task_id=task_id
    )
    return format_response(output)


@mcp.tool(annotations=_DEL_ANN)
def task_delete(project_id: int, task_id: int) -> str:
    """Delete a task.

    Args:
        project_id: The ID of the project.
        task_id: The ID of the task to delete.

    Returns:
        Confirmation message.
    """
    validate_read_only()
    client = get_api_client()
    api = TaskApi(client)
    api.project_project_id_tasks_task_id_delete(
        project_id=project_id, task_id=task_id
    )
    return json.dumps({"status": "deleted", "task_id": task_id})


# ============================================================================
# TEMPLATE MANAGEMENT
# ============================================================================


@mcp.tool(annotations=_RO_ANN)
def template_list(
    project_id: int, sort: str = "name", order: str = "asc"
) -> str:
    """List all templates in a project.

    Args:
        project_id: The ID of the project.
        sort: Field to sort by (name, playbook, etc.).
        order: Sort order (asc or desc).

    Returns:
        JSON list of templates.
    """
    client = get_api_client()
    api = TemplateApi(client)
    templates = api.project_project_id_templates_get(
        project_id=project_id, sort=sort, order=order
    )
    return format_response(templates)


@mcp.tool(annotations=_RO_ANN)
def template_get(project_id: int, template_id: int) -> str:
    """Get details of a specific template.

    Args:
        project_id: The ID of the project.
        template_id: The ID of the template.

    Returns:
        JSON object with template details.
    """
    client = get_api_client()
    api = TemplateApi(client)
    template = api.project_project_id_templates_template_id_get(
        project_id=project_id, template_id=template_id
    )
    return format_response(template)


@mcp.tool(annotations=_RW_ANN)
def template_create(
    project_id: int,
    name: str,
    playbook: str,
    inventory_id: int,
    repository_id: int,
    environment_id: Optional[int] = None,
    description: Optional[str] = None,
    arguments: Optional[str] = None,
    allow_override_args_in_task: bool = False,
    suppress_success_alerts: bool = False,
    app: str = "ansible",
) -> str:
    """Create a new template (job template).

    Args:
        project_id: The ID of the project.
        name: Template name.
        playbook: Playbook filename to run.
        inventory_id: ID of the inventory to use.
        repository_id: ID of the repository containing the playbook.
        environment_id: ID of the environment (optional).
        description: Template description (optional).
        arguments: Extra CLI arguments as JSON array string (optional).
        allow_override_args_in_task: Allow overriding arguments per task.
        suppress_success_alerts: Suppress alerts on success.
        app: Application type ("ansible", "terraform", "tofu"). Defaults to "ansible".

    Returns:
        JSON object with the created template details.
    """
    validate_read_only()
    client = get_api_client()
    api = TemplateApi(client)
    request = TemplateRequest(
        name=name,
        playbook=playbook,
        inventory_id=inventory_id,
        repository_id=repository_id,
        environment_id=environment_id,
        description=description,
        arguments=arguments,
        allow_override_args_in_task=allow_override_args_in_task,
        suppress_success_alerts=suppress_success_alerts,
        project_id=project_id,
        app=app,
    )
    template = api.project_project_id_templates_post(
        project_id=project_id, template_request=request
    )
    return format_response(template)


@mcp.tool(annotations=_DEL_ANN)
def template_delete(project_id: int, template_id: int) -> str:
    """Delete a template.

    Args:
        project_id: The ID of the project.
        template_id: The ID of the template to delete.

    Returns:
        Confirmation message.
    """
    validate_read_only()
    client = get_api_client()
    api = TemplateApi(client)
    api.project_project_id_templates_template_id_delete(
        project_id=project_id, template_id=template_id
    )
    return json.dumps({"status": "deleted", "template_id": template_id})


# ============================================================================
# INVENTORY MANAGEMENT
# ============================================================================


@mcp.tool(annotations=_RO_ANN)
def inventory_list(
    project_id: int, sort: str = "name", order: str = "asc"
) -> str:
    """List all inventories in a project.

    Args:
        project_id: The ID of the project.
        sort: Field to sort by.
        order: Sort order (asc or desc).

    Returns:
        JSON list of inventories.
    """
    client = get_api_client()
    api = InventoryApi(client)
    inventories = api.project_project_id_inventory_get(
        project_id=project_id, sort=sort, order=order
    )
    return format_response(inventories)


@mcp.tool(annotations=_RO_ANN)
def inventory_get(project_id: int, inventory_id: int) -> str:
    """Get details of a specific inventory.

    Args:
        project_id: The ID of the project.
        inventory_id: The ID of the inventory.

    Returns:
        JSON object with inventory details.
    """
    client = get_api_client()
    api = InventoryApi(client)
    inventory = api.project_project_id_inventory_inventory_id_get(
        project_id=project_id, inventory_id=inventory_id
    )
    return format_response(inventory)


@mcp.tool(annotations=_RW_ANN)
def inventory_create(
    project_id: int,
    name: str,
    inventory: str,
    ssh_key_id: int,
    type: str = "static",
    become_key_id: Optional[int] = None,
) -> str:
    """Create a new inventory.

    Args:
        project_id: The ID of the project.
        name: Inventory name.
        inventory: Inventory content (hosts list or path).
        ssh_key_id: ID of the SSH key to use.
        type: Inventory type (static, static-yaml, file).
        become_key_id: ID of the become (sudo) key (optional).

    Returns:
        JSON object with the created inventory details.
    """
    validate_read_only()
    client = get_api_client()
    api = InventoryApi(client)
    request = InventoryRequest(
        name=name,
        inventory=inventory,
        ssh_key_id=ssh_key_id,
        type=type,
        become_key_id=become_key_id,
        project_id=project_id,
    )
    result = api.project_project_id_inventory_post(
        project_id=project_id, inventory_request=request
    )
    return format_response(result)


@mcp.tool(annotations=_DEL_ANN)
def inventory_delete(project_id: int, inventory_id: int) -> str:
    """Delete an inventory.

    Args:
        project_id: The ID of the project.
        inventory_id: The ID of the inventory to delete.

    Returns:
        Confirmation message.
    """
    validate_read_only()
    client = get_api_client()
    api = InventoryApi(client)
    api.project_project_id_inventory_inventory_id_delete(
        project_id=project_id, inventory_id=inventory_id
    )
    return json.dumps({"status": "deleted", "inventory_id": inventory_id})


# ============================================================================
# REPOSITORY MANAGEMENT
# ============================================================================


@mcp.tool(annotations=_RO_ANN)
def repository_list(
    project_id: int, sort: str = "name", order: str = "asc"
) -> str:
    """List all repositories in a project.

    Args:
        project_id: The ID of the project.
        sort: Field to sort by.
        order: Sort order (asc or desc).

    Returns:
        JSON list of repositories.
    """
    client = get_api_client()
    api = RepositoryApi(client)
    repos = api.project_project_id_repositories_get(
        project_id=project_id, sort=sort, order=order
    )
    return format_response(repos)


@mcp.tool(annotations=_RO_ANN)
def repository_get(project_id: int, repository_id: int) -> str:
    """Get details of a specific repository.

    Args:
        project_id: The ID of the project.
        repository_id: The ID of the repository.

    Returns:
        JSON object with repository details.
    """
    client = get_api_client()
    api = RepositoryApi(client)
    repo = api.project_project_id_repositories_repository_id_get(
        project_id=project_id, repository_id=repository_id
    )
    return format_response(repo)


@mcp.tool(annotations=_RW_ANN)
def repository_create(
    project_id: int,
    name: str,
    git_url: str,
    ssh_key_id: int,
    git_branch: str = "main",
) -> str:
    """Create a new repository.

    Args:
        project_id: The ID of the project.
        name: Repository name.
        git_url: Git URL of the repository.
        ssh_key_id: ID of the SSH key for authentication.
        git_branch: Git branch to use (default: main).

    Returns:
        JSON object with the created repository details.
    """
    validate_read_only()
    client = get_api_client()
    api = RepositoryApi(client)
    request = RepositoryRequest(
        name=name,
        git_url=git_url,
        ssh_key_id=ssh_key_id,
        git_branch=git_branch,
        project_id=project_id,
    )
    repo = api.project_project_id_repositories_post(
        project_id=project_id, repository_request=request
    )
    return format_response(repo)


@mcp.tool(annotations=_DEL_ANN)
def repository_delete(project_id: int, repository_id: int) -> str:
    """Delete a repository.

    Args:
        project_id: The ID of the project.
        repository_id: The ID of the repository to delete.

    Returns:
        Confirmation message.
    """
    validate_read_only()
    client = get_api_client()
    api = RepositoryApi(client)
    api.project_project_id_repositories_repository_id_delete(
        project_id=project_id, repository_id=repository_id
    )
    return json.dumps({"status": "deleted", "repository_id": repository_id})


# ============================================================================
# ENVIRONMENT MANAGEMENT
# ============================================================================


@mcp.tool(annotations=_RO_ANN)
def environment_list(
    project_id: int, sort: str = "name", order: str = "asc"
) -> str:
    """List all environments in a project.

    Args:
        project_id: The ID of the project.
        sort: Field to sort by.
        order: Sort order (asc or desc).

    Returns:
        JSON list of environments.
    """
    client = get_api_client()
    api = VariableGroupApi(client)
    environments = api.project_project_id_environment_get(
        project_id=project_id, sort=sort, order=order
    )
    return format_response(environments)


@mcp.tool(annotations=_RO_ANN)
def environment_get(project_id: int, environment_id: int) -> str:
    """Get details of a specific environment.

    Args:
        project_id: The ID of the project.
        environment_id: The ID of the environment.

    Returns:
        JSON object with environment details.
    """
    client = get_api_client()
    api = VariableGroupApi(client)
    env = api.project_project_id_environment_environment_id_get(
        project_id=project_id, environment_id=environment_id
    )
    return format_response(env)


@mcp.tool(annotations=_RW_ANN)
def environment_create(
    project_id: int,
    name: str,
    json_data: str = "{}",
    password: Optional[str] = None,
) -> str:
    """Create a new environment.

    Args:
        project_id: The ID of the project.
        name: Environment name.
        json_data: JSON string with environment variables.
        password: Optional password for the environment.

    Returns:
        JSON object with the created environment details.
    """
    validate_read_only()
    client = get_api_client()
    api = VariableGroupApi(client)
    request = EnvironmentRequest(
        name=name,
        json=json_data,
        password=password,
        project_id=project_id,
    )
    env = api.project_project_id_environment_post(
        project_id=project_id, environment_request=request
    )
    return format_response(env)


@mcp.tool(annotations=_DEL_ANN)
def environment_delete(project_id: int, environment_id: int) -> str:
    """Delete an environment.

    Args:
        project_id: The ID of the project.
        environment_id: The ID of the environment to delete.

    Returns:
        Confirmation message.
    """
    validate_read_only()
    client = get_api_client()
    api = VariableGroupApi(client)
    api.project_project_id_environment_environment_id_delete(
        project_id=project_id, environment_id=environment_id
    )
    return json.dumps({"status": "deleted", "environment_id": environment_id})


# ============================================================================
# KEY STORE MANAGEMENT
# ============================================================================


@mcp.tool(annotations=_RO_ANN)
def key_list(project_id: int, sort: str = "name", order: str = "asc") -> str:
    """List all keys (credentials) in a project.

    Args:
        project_id: The ID of the project.
        sort: Field to sort by.
        order: Sort order (asc or desc).

    Returns:
        JSON list of keys.
    """
    client = get_api_client()
    api = KeyStoreApi(client)
    keys = api.project_project_id_keys_get(
        project_id=project_id, sort=sort, order=order
    )
    return format_response(keys)


@mcp.tool(annotations=_RO_ANN)
def key_get(project_id: int, key_id: int) -> str:
    """Get details of a specific key.

    Args:
        project_id: The ID of the project.
        key_id: The ID of the key.

    Returns:
        JSON object with key details.
    """
    client = get_api_client()
    # Generated KeyStoreApi has list/create/update/delete but no single-key GET.
    key = _client_get(
        client,
        "/project/{project_id}/keys/{key_id}",
        {"project_id": project_id, "key_id": key_id},
        "AccessKey",
    )
    return format_response(key)


@mcp.tool(annotations=_DEL_ANN)
def key_delete(project_id: int, key_id: int) -> str:
    """Delete a key.

    Args:
        project_id: The ID of the project.
        key_id: The ID of the key to delete.

    Returns:
        Confirmation message.
    """
    validate_read_only()
    client = get_api_client()
    api = KeyStoreApi(client)
    api.project_project_id_keys_key_id_delete(
        project_id=project_id, key_id=key_id
    )
    return json.dumps({"status": "deleted", "key_id": key_id})


# ============================================================================
# SCHEDULE MANAGEMENT
# ============================================================================


@mcp.tool(annotations=_RO_ANN)
def schedule_list(project_id: int) -> str:
    """List all schedules in a project.

    Args:
        project_id: The ID of the project.

    Returns:
        JSON list of schedules.
    """
    client = get_api_client()
    # Generated ScheduleApi exposes create/get-by-id/update/delete but not list.
    schedules = _client_get(
        client,
        "/project/{project_id}/schedules",
        {"project_id": project_id},
        "List[Schedule]",
    )
    return format_response(schedules)


@mcp.tool(annotations=_RW_ANN)
def schedule_create(
    project_id: int,
    template_id: int,
    cron_format: str,
    name: Optional[str] = None,
) -> str:
    """Create a new schedule for a template.

    Args:
        project_id: The ID of the project.
        template_id: The ID of the template to schedule.
        cron_format: Cron expression for the schedule.
        name: Optional name for the schedule.

    Returns:
        JSON object with the created schedule details.
    """
    validate_read_only()
    client = get_api_client()
    api = ScheduleApi(client)
    request = ScheduleRequest(
        template_id=template_id,
        cron_format=cron_format,
        name=name,
        project_id=project_id,
    )
    schedule = api.project_project_id_schedules_post(
        project_id=project_id, schedule_request=request
    )
    return format_response(schedule)


@mcp.tool(annotations=_DEL_ANN)
def schedule_delete(project_id: int, schedule_id: int) -> str:
    """Delete a schedule.

    Args:
        project_id: The ID of the project.
        schedule_id: The ID of the schedule to delete.

    Returns:
        Confirmation message.
    """
    validate_read_only()
    client = get_api_client()
    api = ScheduleApi(client)
    api.project_project_id_schedules_schedule_id_delete(
        project_id=project_id, schedule_id=schedule_id
    )
    return json.dumps({"status": "deleted", "schedule_id": schedule_id})


# ============================================================================
# USER MANAGEMENT
# ============================================================================


@mcp.tool(annotations=_RO_ANN)
def user_get_current() -> str:
    """Get the current authenticated user's information.

    Returns:
        JSON object with current user details.
    """
    client = get_api_client()
    api = UserApi(client)
    user = api.user_get()
    return format_response(user)


@mcp.tool(annotations=_RO_ANN)
def user_tokens() -> str:
    """List API tokens for the current user.

    Returns:
        JSON list of API tokens.
    """
    client = get_api_client()
    api = UserApi(client)
    tokens = api.user_tokens_get()
    return format_response(tokens)


# ============================================================================
# EVENTS
# ============================================================================


@mcp.tool(annotations=_RO_ANN)
def event_list(project_id: int) -> str:
    """List events for a project.

    Args:
        project_id: The ID of the project.

    Returns:
        JSON list of events.
    """
    client = get_api_client()
    api = ProjectApi(client)
    events = api.project_project_id_events_get(project_id=project_id)
    return format_response(events)


# ============================================================================
# SERVER INFO
# ============================================================================


@mcp.tool(annotations=_RO_ANN)
def server_info() -> str:
    """Get Semaphore server information (version, configuration).

    Returns:
        JSON object with server info.
    """
    client = get_api_client()
    api = DefaultApi(client)
    info = api.info_get()
    return format_response(info)


@mcp.tool(annotations=_RO_ANN)
def server_ping() -> str:
    """Ping the Semaphore server to check connectivity.

    Returns:
        Ping response confirming the server is reachable.
    """
    client = get_api_client()
    api = DefaultApi(client)
    result = api.ping_get()
    return json.dumps({"status": "ok", "response": str(result)})


def main():
    """Run the Semaphore MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
