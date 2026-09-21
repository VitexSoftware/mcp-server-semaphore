# Semaphore MCP Server

![Semaphore MCP Server](semaphore-mcp-server.svg?raw=true)
![Packaging: deb](https://img.shields.io/badge/packaging-.deb-red?logo=debian&logoColor=white)
[![M8ven Score](https://m8ven.ai/badge/mcp/vitexsoftware-semaphore-mcp-server-r7vina)](https://m8ven.ai/mcp/vitexsoftware-semaphore-mcp-server-r7vina)

A Model Context Protocol (MCP) server for [Semaphore UI](https://semaphoreui.com/) - the modern open-source alternative to Ansible Tower/AWX.

This server enables AI assistants and MCP-compatible tools to interact with Semaphore UI for managing Ansible, Terraform, and other automation workflows.

## Features

- **Project Management** — List, create, and delete projects
- **Task Management** — Launch, monitor, stop, and retrieve output of tasks
- **Template Management** — CRUD operations on job templates
- **Inventory Management** — Manage Ansible inventories
- **Repository Management** — Manage Git repositories
- **Environment Management** — Manage environment variable sets
- **Key Store** — List and manage SSH keys and credentials
- **Schedule Management** — Create and manage cron-based schedules
- **User & Events** — Get user info and project event logs
- **Server Info** — Check server health and version

## Installation

```bash
pip install -e .
```

Or with the semaphore client from a local path:

```bash
pip install -e /path/to/python3-semaphore-client
pip install -e .
```

## Configuration

Copy `.env.example` to `.env` and configure:

```bash
cp .env.example .env
```

Required environment variables:

| Variable | Description |
|----------|-------------|
| `SEMAPHORE_URL` | Base URL of your Semaphore UI instance (e.g., `http://localhost:3000`) |
| `SEMAPHORE_TOKEN` | API Bearer token (create via Semaphore UI or API) |

Optional environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `READ_ONLY` | `true` | Set to `false` to enable write operations |
| `DEBUG` | _(unset)_ | Set to `true` for verbose logging |

### Creating an API Token

1. **Via Web UI** (Semaphore 2.14+): Go to your user settings and create a token
2. **Via API**:
   ```bash
   # Login
   curl -c /tmp/semaphore-cookie -XPOST \
     -H 'Content-Type: application/json' \
     -d '{"auth": "YOUR_LOGIN", "password": "YOUR_PASSWORD"}' \
     http://localhost:3000/api/auth/login

   # Generate token
   curl -b /tmp/semaphore-cookie -XPOST \
     http://localhost:3000/api/user/tokens
   ```

## Usage

### Running the MCP Server

```bash
semaphore-mcp
```

### MCP Configuration

Add to your MCP client configuration (e.g., VS Code `mcp.json`):

```json
{
  "servers": {
    "semaphore": {
      "command": "semaphore-mcp",
      "env": {
        "SEMAPHORE_URL": "http://localhost:3000",
        "SEMAPHORE_TOKEN": "your-token-here",
        "READ_ONLY": "false"
      }
    }
  }
}
```

Or for Claude Desktop (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "semaphore": {
      "command": "semaphore-mcp",
      "env": {
        "SEMAPHORE_URL": "http://localhost:3000",
        "SEMAPHORE_TOKEN": "your-token-here"
      }
    }
  }
}
```

## Available Tools

Tools declare MCP annotations (`readOnlyHint`, `destructiveHint`, …). Write tools
call `validate_read_only()` and refuse when `READ_ONLY=true` (default).

| Tool | Description | Mode |
|------|-------------|------|
| `project_list` | List all projects | read |
| `project_get` | Get project details | read |
| `project_create` | Create a new project | write |
| `project_delete` | Delete a project | write |
| `task_list` | List tasks in a project | read |
| `task_get` | Get task details | read |
| `task_launch` | Launch a task from a template | write |
| `task_stop` | Stop a running task | write |
| `task_output` | Get task output/log | read |
| `task_delete` | Delete a task | write |
| `template_list` | List templates in a project | read |
| `template_get` | Get template details | read |
| `template_create` | Create a new template | write |
| `template_delete` | Delete a template | write |
| `inventory_list` | List inventories in a project | read |
| `inventory_get` | Get inventory details | read |
| `inventory_create` | Create a new inventory | write |
| `inventory_delete` | Delete an inventory | write |
| `repository_list` | List repositories in a project | read |
| `repository_get` | Get repository details | read |
| `repository_create` | Create a new repository | write |
| `repository_delete` | Delete a repository | write |
| `environment_list` | List environments in a project | read |
| `environment_get` | Get environment details | read |
| `environment_create` | Create a new environment | write |
| `environment_delete` | Delete an environment | write |
| `key_list` | List keys/credentials in a project | read |
| `key_get` | Get key details | read |
| `key_delete` | Delete a key | write |
| `schedule_list` | List schedules in a project | read |
| `schedule_create` | Create a new schedule | write |
| `schedule_delete` | Delete a schedule | write |
| `user_get_current` | Get current user info | read |
| `user_tokens` | List user API tokens | read |
| `event_list` | List project events | read |
| `server_info` | Get server version/info | read |
| `server_ping` | Check server connectivity | read |

When `READ_ONLY=true` (default), create/update/delete/launch/stop tools raise a
clear error. Set `READ_ONLY=false` to allow mutating operations.

## Dependencies

This project uses [python3-semaphore-client](https://github.com/VitexSoftware/python3-semaphore-client) — an OpenAPI-generated Python client library for the Semaphore UI API (v2.16.14).

## Development

```bash
# Install in development mode
pip install -e ".[dev]"

# Run directly
python -m semaphore_mcp.semaphore_mcp_server
```

### Live capability scenario

Exercises every read tool against a real Semaphore instance and verifies that
write tools refuse under `READ_ONLY=true`:

```bash
SEMAPHORE_URL=https://semaphore.example.com \
SEMAPHORE_TOKEN=... READ_ONLY=true \
  python tests/live_capability_scenario.py --json-out /tmp/semaphore-live.json
```

Or with CLI flags:

```bash
python tests/live_capability_scenario.py \
  --url https://semaphore.example.com \
  --token "$SEMAPHORE_TOKEN" \
  --json-out /tmp/semaphore-live.json
```

Exit code is non-zero when any non-skipped check fails.

## License

MIT
