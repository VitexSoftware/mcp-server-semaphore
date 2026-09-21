#!/usr/bin/env python3
"""Live capability scenario for Semaphore MCP Server.

Exercises every MCP tool against a real Semaphore UI instance and reports
whether each capability returns usable data (or correctly refuses writes under
READ_ONLY).

Usage:
  SEMAPHORE_URL=https://semaphore.example.com \\
  SEMAPHORE_TOKEN=... READ_ONLY=true \\
    python tests/live_capability_scenario.py

  python tests/live_capability_scenario.py \\
    --url https://semaphore.example.com --token ... \\
    --json-out /tmp/semaphore-live.json

Exit code is 0 only when every non-skipped check passes.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@dataclass
class CheckResult:
    name: str
    kind: str  # tool | meta | guard
    ok: bool
    detail: str = ""
    sample: Any = None
    skipped: bool = False


@dataclass
class ScenarioReport:
    url: str
    results: List[CheckResult] = field(default_factory=list)

    def add(self, result: CheckResult) -> None:
        self.results.append(result)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.ok and not r.skipped)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if not r.ok and not r.skipped)

    @property
    def skipped(self) -> int:
        return sum(1 for r in self.results if r.skipped)


def _parse_payload(data: Any) -> Any:
    if isinstance(data, str):
        try:
            return json.loads(data)
        except (json.JSONDecodeError, TypeError):
            return data
    return data


def _is_error_payload(data: Any) -> Optional[str]:
    data = _parse_payload(data)
    if isinstance(data, str):
        low = data.lower()
        if "error" in low or "traceback" in low or "exception" in low:
            return data[:300]
        return None
    if not isinstance(data, dict):
        return None
    if data.get("error") is True or data.get("success") is False:
        return str(data.get("message") or data.get("reason") or data)[:300]
    return None


def _has_usable_data(data: Any) -> Tuple[bool, str]:
    data = _parse_payload(data)
    err = _is_error_payload(data)
    if err:
        return False, err
    if data is None:
        return False, "null response"
    if isinstance(data, str):
        return (bool(data.strip()), "empty string" if not data.strip() else "ok string")
    if isinstance(data, list):
        return (True, f"list len={len(data)}")
    if isinstance(data, dict):
        if data.get("status") == "ok":
            return True, "status=ok"
        if data:
            return True, f"keys={list(data.keys())[:8]}"
        return False, "empty object"
    return True, f"type={type(data).__name__}"


def _tool_is_readonly(tool: Any) -> bool:
    ann = getattr(tool, "annotations", None)
    if ann is None:
        return True
    if hasattr(ann, "read_only_hint"):
        return bool(ann.read_only_hint)
    if hasattr(ann, "readOnlyHint"):
        return bool(ann.readOnlyHint)
    if isinstance(ann, dict):
        return bool(ann.get("read_only_hint", ann.get("readOnlyHint", True)))
    return True


def _first_id(payload: Any, *keys: str) -> Optional[int]:
    data = _parse_payload(payload)
    items: List[Any] = []
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        for k in ("items", "data", "results", "projects", "tasks", "templates"):
            if isinstance(data.get(k), list):
                items = data[k]
                break
        if not items and data.get("id") is not None:
            try:
                return int(data["id"])
            except (TypeError, ValueError):
                return None
    if not items:
        return None
    first = items[0]
    if not isinstance(first, dict):
        return None
    for key in keys or ("id",):
        if first.get(key) is not None:
            try:
                return int(first[key])
            except (TypeError, ValueError):
                continue
    return None


def _run_check(
    report: ScenarioReport,
    name: str,
    kind: str,
    fn: Callable[[], Any],
    *,
    require_data: bool = True,
    skip_reason: Optional[str] = None,
) -> Optional[Any]:
    if skip_reason:
        report.add(CheckResult(name=name, kind=kind, ok=True, detail=skip_reason, skipped=True))
        return None
    try:
        raw = fn()
        ok, detail = _has_usable_data(raw) if require_data else (True, "invoked")
        sample = _parse_payload(raw)
        try:
            preview = json.dumps(sample, ensure_ascii=False, default=str)
        except TypeError:
            preview = str(sample)
        report.add(
            CheckResult(
                name=name,
                kind=kind,
                ok=ok,
                detail=detail,
                sample=preview[:800],
            )
        )
        return raw
    except Exception as exc:  # noqa: BLE001 — scenario must keep going
        report.add(
            CheckResult(
                name=name,
                kind=kind,
                ok=False,
                detail=f"{type(exc).__name__}: {exc}",
                sample=traceback.format_exc()[-600:],
            )
        )
        return None


def _assert_readonly_guard(
    report: ScenarioReport, name: str, fn: Callable[[], Any]
) -> None:
    try:
        raw = fn()
        payload = _parse_payload(raw)
        refused = False
        if isinstance(payload, dict) and (
            "read-only" in str(payload).lower() or payload.get("success") is False
        ):
            refused = True
        report.add(
            CheckResult(
                name=f"readonly_guard:{name}",
                kind="guard",
                ok=refused,
                detail="write returned without raising" if not refused else "refused in payload",
                sample=str(payload)[:300],
            )
        )
    except ValueError as exc:
        ok = "read-only" in str(exc).lower()
        report.add(
            CheckResult(
                name=f"readonly_guard:{name}",
                kind="guard",
                ok=ok,
                detail=str(exc),
            )
        )
    except Exception as exc:  # noqa: BLE001
        report.add(
            CheckResult(
                name=f"readonly_guard:{name}",
                kind="guard",
                ok=False,
                detail=f"unexpected {type(exc).__name__}: {exc}",
            )
        )


def run_scenario(
    url: str,
    token: str,
    *,
    read_only: bool = True,
) -> ScenarioReport:
    os.environ["SEMAPHORE_URL"] = url
    os.environ["SEMAPHORE_TOKEN"] = token
    os.environ["READ_ONLY"] = "true" if read_only else "false"

    import importlib
    import semaphore_mcp.semaphore_mcp_server as server

    server._api_client = None
    server = importlib.reload(server)
    server._api_client = None

    report = ScenarioReport(url=url)
    tools = asyncio.run(server.mcp.list_tools())
    tool_by_name = {t.name: t for t in tools}
    fn_by_name = {
        name: getattr(server, name)
        for name in tool_by_name
        if callable(getattr(server, name, None))
    }

    report.add(
        CheckResult(
            name="tool_catalog",
            kind="meta",
            ok=len(tools) == 37,
            detail=f"{len(tools)} tools registered (expect 37)",
        )
    )
    ro_count = sum(1 for t in tools if _tool_is_readonly(t))
    rw_count = len(tools) - ro_count
    report.add(
        CheckResult(
            name="tool_annotations",
            kind="meta",
            ok=ro_count > 0 and rw_count > 0,
            detail=f"read_only={ro_count} write={rw_count}",
        )
    )

    # ---- server / user (no project id) ----
    _run_check(report, "server_ping", "tool", server.server_ping)
    _run_check(report, "server_info", "tool", server.server_info)
    _run_check(report, "user_get_current", "tool", server.user_get_current)
    _run_check(report, "user_tokens", "tool", server.user_tokens)

    projects = _run_check(report, "project_list", "tool", server.project_list)
    project_id = _first_id(projects, "id")

    _run_check(
        report,
        "project_get",
        "tool",
        lambda: server.project_get(project_id=project_id),
        skip_reason=None if project_id is not None else "no project id",
    )

    # ---- project-scoped list tools ----
    tasks = _run_check(
        report,
        "task_list",
        "tool",
        lambda: server.task_list(project_id=project_id),
        skip_reason=None if project_id is not None else "no project id",
    )
    task_id = _first_id(tasks, "id")

    templates = _run_check(
        report,
        "template_list",
        "tool",
        lambda: server.template_list(project_id=project_id),
        skip_reason=None if project_id is not None else "no project id",
    )
    template_id = _first_id(templates, "id")

    inventories = _run_check(
        report,
        "inventory_list",
        "tool",
        lambda: server.inventory_list(project_id=project_id),
        skip_reason=None if project_id is not None else "no project id",
    )
    inventory_id = _first_id(inventories, "id")

    repos = _run_check(
        report,
        "repository_list",
        "tool",
        lambda: server.repository_list(project_id=project_id),
        skip_reason=None if project_id is not None else "no project id",
    )
    repository_id = _first_id(repos, "id")

    envs = _run_check(
        report,
        "environment_list",
        "tool",
        lambda: server.environment_list(project_id=project_id),
        skip_reason=None if project_id is not None else "no project id",
    )
    environment_id = _first_id(envs, "id")

    keys = _run_check(
        report,
        "key_list",
        "tool",
        lambda: server.key_list(project_id=project_id),
        skip_reason=None if project_id is not None else "no project id",
    )
    key_id = _first_id(keys, "id")

    _run_check(
        report,
        "schedule_list",
        "tool",
        lambda: server.schedule_list(project_id=project_id),
        skip_reason=None if project_id is not None else "no project id",
    )
    _run_check(
        report,
        "event_list",
        "tool",
        lambda: server.event_list(project_id=project_id),
        skip_reason=None if project_id is not None else "no project id",
    )

    # ---- id-dependent reads ----
    _run_check(
        report,
        "task_get",
        "tool",
        lambda: server.task_get(project_id=project_id, task_id=task_id),
        skip_reason=None if (project_id is not None and task_id is not None) else "no task id",
    )
    _run_check(
        report,
        "task_output",
        "tool",
        lambda: server.task_output(project_id=project_id, task_id=task_id),
        skip_reason=None if (project_id is not None and task_id is not None) else "no task id",
    )
    _run_check(
        report,
        "template_get",
        "tool",
        lambda: server.template_get(project_id=project_id, template_id=template_id),
        skip_reason=None
        if (project_id is not None and template_id is not None)
        else "no template id",
    )
    _run_check(
        report,
        "inventory_get",
        "tool",
        lambda: server.inventory_get(project_id=project_id, inventory_id=inventory_id),
        skip_reason=None
        if (project_id is not None and inventory_id is not None)
        else "no inventory id",
    )
    _run_check(
        report,
        "repository_get",
        "tool",
        lambda: server.repository_get(project_id=project_id, repository_id=repository_id),
        skip_reason=None
        if (project_id is not None and repository_id is not None)
        else "no repository id",
    )
    _run_check(
        report,
        "environment_get",
        "tool",
        lambda: server.environment_get(project_id=project_id, environment_id=environment_id),
        skip_reason=None
        if (project_id is not None and environment_id is not None)
        else "no environment id",
    )
    _run_check(
        report,
        "key_get",
        "tool",
        lambda: server.key_get(project_id=project_id, key_id=key_id),
        skip_reason=None if (project_id is not None and key_id is not None) else "no key id",
    )

    covered = {r.name.split(":")[0] for r in report.results if r.kind == "tool"}
    for t in tools:
        if not _tool_is_readonly(t):
            continue
        if t.name in covered:
            continue
        fn = fn_by_name.get(t.name)
        if not fn:
            report.add(
                CheckResult(
                    name=t.name,
                    kind="tool",
                    ok=False,
                    detail="registered in MCP but missing Python callable",
                )
            )
            continue
        report.add(
            CheckResult(
                name=t.name,
                kind="tool",
                ok=True,
                detail="no default args probe defined",
                skipped=True,
            )
        )

    # ---- READ_ONLY guards on mutating tools ----
    if read_only:
        pid = project_id if project_id is not None else 1
        sample_writes = [
            ("project_create", lambda: server.project_create(name="mcp-live-guard")),
            ("project_delete", lambda: server.project_delete(project_id=pid)),
            (
                "task_launch",
                lambda: server.task_launch(
                    project_id=pid, template_id=template_id or 1
                ),
            ),
            ("task_stop", lambda: server.task_stop(project_id=pid, task_id=task_id or 1)),
            (
                "task_delete",
                lambda: server.task_delete(project_id=pid, task_id=task_id or 1),
            ),
            (
                "template_create",
                lambda: server.template_create(
                    project_id=pid,
                    name="mcp-live-guard",
                    playbook="noop.yml",
                    inventory_id=inventory_id or 1,
                    repository_id=repository_id or 1,
                ),
            ),
            (
                "template_delete",
                lambda: server.template_delete(
                    project_id=pid, template_id=template_id or 1
                ),
            ),
            (
                "inventory_create",
                lambda: server.inventory_create(
                    project_id=pid,
                    name="mcp-live-guard",
                    inventory="localhost",
                    ssh_key_id=key_id or 1,
                ),
            ),
            (
                "inventory_delete",
                lambda: server.inventory_delete(
                    project_id=pid, inventory_id=inventory_id or 1
                ),
            ),
            (
                "repository_create",
                lambda: server.repository_create(
                    project_id=pid,
                    name="mcp-live-guard",
                    git_url="git@example.com:x.git",
                    ssh_key_id=key_id or 1,
                ),
            ),
            (
                "repository_delete",
                lambda: server.repository_delete(
                    project_id=pid, repository_id=repository_id or 1
                ),
            ),
            (
                "environment_create",
                lambda: server.environment_create(project_id=pid, name="mcp-live-guard"),
            ),
            (
                "environment_delete",
                lambda: server.environment_delete(
                    project_id=pid, environment_id=environment_id or 1
                ),
            ),
            ("key_delete", lambda: server.key_delete(project_id=pid, key_id=key_id or 1)),
            (
                "schedule_create",
                lambda: server.schedule_create(
                    project_id=pid,
                    template_id=template_id or 1,
                    cron_format="0 0 * * *",
                ),
            ),
            (
                "schedule_delete",
                lambda: server.schedule_delete(project_id=pid, schedule_id=1),
            ),
        ]
        for name, fn in sample_writes:
            _assert_readonly_guard(report, name, fn)

    for t in tools:
        if _tool_is_readonly(t):
            continue
        report.add(
            CheckResult(
                name=f"catalog:{t.name}",
                kind="meta",
                ok=True,
                detail="write tool registered (guard-sampled separately)",
            )
        )

    _ = tool_by_name
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=os.getenv("SEMAPHORE_URL"))
    parser.add_argument("--token", default=os.getenv("SEMAPHORE_TOKEN"))
    parser.add_argument("--json-out", help="Write full report JSON here")
    parser.add_argument(
        "--allow-writes",
        action="store_true",
        help="Set READ_ONLY=false (guards skipped)",
    )
    args = parser.parse_args()

    missing = [
        n
        for n, v in [
            ("--url/SEMAPHORE_URL", args.url),
            ("--token/SEMAPHORE_TOKEN", args.token),
        ]
        if not v
    ]
    if missing:
        print(f"Missing required config: {', '.join(missing)}", file=sys.stderr)
        return 2

    report = run_scenario(
        args.url,
        args.token,
        read_only=not args.allow_writes,
    )

    print(f"Semaphore MCP live scenario: {report.url}")
    print(f"passed={report.passed} failed={report.failed} skipped={report.skipped}")
    print()
    for r in report.results:
        if r.skipped:
            flag = "SKIP"
        elif r.ok:
            flag = "PASS"
        else:
            flag = "FAIL"
        print(f"  {flag:4} [{r.kind}] {r.name}: {r.detail}")

    if args.json_out:
        out = {
            "url": report.url,
            "passed": report.passed,
            "failed": report.failed,
            "skipped": report.skipped,
            "results": [r.__dict__ for r in report.results],
        }
        Path(args.json_out).write_text(
            json.dumps(out, indent=2, ensure_ascii=False, default=str)
        )
        print(f"\nWrote {args.json_out}")

    return 0 if report.failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
