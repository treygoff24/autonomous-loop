from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .controller import AutonomousLoopRuntime, DEFAULT_RETENTION_HOURS, DEFAULT_STALE_HOURS
from .hooks import parse_hook_input


def _json_arg(value: str) -> Any:
    return json.loads(value)


def _csv_arg(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="autonomous-loop")
    parser.add_argument("--runtime-root", type=Path, default=None)
    subparsers = parser.add_subparsers(dest="command", required=True)

    request = subparsers.add_parser("request")
    request_sub = request.add_subparsers(dest="action", required=True)

    enable = request_sub.add_parser("enable")
    enable.add_argument("--cwd", required=True)
    enable.add_argument("--objective", required=True)
    enable.add_argument("--task-json", action="append", default=[])
    enable.add_argument("--gate-profile")
    enable.add_argument("--max-stop-iterations", type=int)

    for name in ("pause", "resume", "disable", "release"):
        action = request_sub.add_parser(name)
        action.add_argument("--cwd", required=True)
        action.add_argument("--reason")

    hook = subparsers.add_parser("hook")
    hook_sub = hook.add_subparsers(dest="hook_name", required=True)
    hook_sub.add_parser("stop")
    hook_sub.add_parser("session-start")

    install = subparsers.add_parser("install-repo")
    install.add_argument("--repo", required=True)
    install.add_argument("--force", action="store_true")
    install.add_argument("--package-manager")
    install.add_argument("--prefer-scripts", type=_csv_arg)

    cleanup = subparsers.add_parser("cleanup")
    cleanup.add_argument("--cwd", required=True)
    cleanup.add_argument("--stale-hours", type=int, default=DEFAULT_STALE_HOURS)
    cleanup.add_argument("--retention-hours", type=int, default=DEFAULT_RETENTION_HOURS)

    bootstrap = subparsers.add_parser("bootstrap")
    bootstrap.add_argument("--force", action="store_true")

    doctor = subparsers.add_parser("doctor")
    doctor.add_argument("--cwd")

    status = subparsers.add_parser("status")
    status.add_argument("--cwd", required=True)
    status.add_argument("--session-id")

    return parser


def emit_json(payload: Any) -> None:
    json.dump(payload, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    runtime = AutonomousLoopRuntime(root=args.runtime_root)

    if args.command == "request":
        if args.action == "enable":
            tasks = [_json_arg(item) for item in args.task_json]
            emit_json(
                runtime.request_enable(
                    cwd=args.cwd,
                    objective=args.objective,
                    task_json=tasks or None,
                    gate_profile=args.gate_profile,
                    max_stop_iterations=args.max_stop_iterations,
                )
            )
            return 0
        emit_json(runtime.request_action(args.action, cwd=args.cwd, reason=args.reason))
        return 0

    if args.command == "hook":
        payload = parse_hook_input(sys.stdin.read())
        if args.hook_name == "stop":
            output = runtime.handle_stop_payload(payload)
        else:
            output = runtime.handle_session_start_payload(payload)
        if output is not None:
            emit_json(output)
        return 0

    if args.command == "install-repo":
        result = runtime.install_repo(
            args.repo,
            force=args.force,
            package_manager=args.package_manager,
            prefer_scripts=args.prefer_scripts,
        )
        emit_json(result)
        return 1 if result.get("ok") is False else 0

    if args.command == "cleanup":
        result = runtime.cleanup(
            cwd=args.cwd,
            stale_hours=args.stale_hours,
            retention_hours=args.retention_hours,
        )
        emit_json(result)
        return 1 if result.get("ok") is False else 0

    if args.command == "bootstrap":
        result = runtime.bootstrap(force=args.force)
        emit_json(result)
        return 1 if result.get("ok") is False else 0

    if args.command == "doctor":
        result = runtime.doctor(cwd=args.cwd)
        emit_json(result)
        return 1 if result.get("ok") is False else 0

    if args.command == "status":
        emit_json(runtime.status(args.cwd, session_id=args.session_id))
        return 0

    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
