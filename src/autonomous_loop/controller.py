from __future__ import annotations

import os
import secrets
import shutil
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .bootstrap import build_machine_config, detect_codex_version, resolve_cli_path, validate_machine_config
from .gates import run_command, run_gate_profile
from .hashes import stable_hash
from .hooks import parse_claim_nonce, stop_block, stop_hard_stop
from .install_repo import InstallRepoFailure, inspect_repo
from .locks import file_lock
from .logging_utils import build_file_logger
from .models import Namespace, PendingRequest, RuntimeState, utc_now
from .paths import RuntimePaths, hash_text, repo_hash_for
from .storage import RuntimeStore, atomic_write_json, read_json

DEFAULT_STALE_HOURS = 8
DEFAULT_RETENTION_HOURS = 24


def _check_hooks_match(hooks_json: Any, machine_config: dict[str, Any]) -> tuple[bool, str | None]:
    """Return (True, None) if hooks stop command matches machine config, else (False, reason)."""
    try:
        stop_command = hooks_json["hooks"]["Stop"][0]["hooks"][0]["command"] if hooks_json else None
    except (KeyError, IndexError, TypeError):
        stop_command = None
    if stop_command != machine_config["hook_commands"]["stop"]:
        return False, "stop command does not match machine config"
    return True, None


def _paths_equivalent(left: str | Path, right: str | Path) -> bool:
    try:
        return Path(left).expanduser().resolve() == Path(right).expanduser().resolve()
    except OSError:
        return False


def _parse_utc_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _timestamp_older_than(value: str | None, cutoff: datetime) -> bool:
    parsed = _parse_utc_timestamp(value)
    if parsed is None:
        return False
    return parsed <= cutoff


def _archive_move(source: Path, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists():
        shutil.move(str(source), str(destination))
        return destination

    counter = 1
    while True:
        candidate = destination.with_name(f"{destination.name}-{counter}")
        if not candidate.exists():
            shutil.move(str(source), str(candidate))
            return candidate
        counter += 1


def _state_activity_timestamp(state: RuntimeState) -> str:
    return state.heartbeat_at or state.updated_at or state.created_at


def _default_limits(project_config: dict[str, Any]) -> dict[str, int]:
    defaults = project_config.get("defaults", {})
    return {
        "maxStopIterations": int(defaults.get("maxStopIterations", 12)),
        "maxRepeatedFailureSignature": int(defaults.get("maxRepeatedFailureSignature", 3)),
    }


def _codex_session_binding() -> tuple[str, str] | tuple[None, None]:
    for env_name in ("CODEX_SESSION_ID", "CODEX_THREAD_ID"):
        value = os.environ.get(env_name)
        if value:
            return value, env_name
    return None, None


def _minimal_contract(objective: str, project_config: dict[str, Any], max_iterations: int) -> dict[str, Any]:
    defaults = project_config.get("defaults", {})
    gate_profile = str(defaults.get("gateProfile", "default"))
    return {
        "version": "0.1",
        "contractId": hash_text(objective)[:12],
        "objective": objective,
        "mode": "implement-until-done",
        "gateProfile": gate_profile,
        "tasks": [
            {
                "id": "T1",
                "title": "Implement the agreed change set",
                "dependsOn": [],
                "required": True,
                "evidence": [{"kind": "pathChanged", "glob": "**/*"}],
            }
        ],
        "limits": {
            "maxStopIterations": max_iterations,
            "maxRepeatedFailureSignature": int(defaults.get("maxRepeatedFailureSignature", 3)),
        },
        "policy": {
            "contractEditableByAgent": False,
            "semanticReview": project_config.get("semanticReview", "advisory-after-green"),
        },
    }


def _normalize_contract(contract: dict[str, Any], project_config: dict[str, Any]) -> dict[str, Any]:
    payload = deepcopy(contract)
    payload.setdefault("version", "0.1")
    payload.setdefault("contractId", hash_text(payload.get("objective", "contract"))[:12])
    payload.setdefault("objective", "Implement the agreed plan to completion")
    payload.setdefault("mode", "implement-until-done")
    payload.setdefault("gateProfile", project_config.get("defaults", {}).get("gateProfile", "default"))
    payload.setdefault("tasks", [])
    payload.setdefault("limits", _default_limits(project_config))
    payload.setdefault(
        "policy",
        {
            "contractEditableByAgent": False,
            "semanticReview": project_config.get("semanticReview", "advisory-after-green"),
        },
    )
    normalized_tasks: list[dict[str, Any]] = []
    for index, task in enumerate(payload["tasks"], start=1):
        item = dict(task)
        item.setdefault("id", f"T{index}")
        item.setdefault("title", f"Task {index}")
        item.setdefault("dependsOn", [])
        item.setdefault("required", True)
        item.setdefault("evidence", [])
        normalized_tasks.append(item)
    if not normalized_tasks:
        normalized_tasks = _minimal_contract(str(payload["objective"]), project_config, int(payload["limits"]["maxStopIterations"]))["tasks"]
    payload["tasks"] = normalized_tasks
    return payload


def _hash_file(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _matching_paths(repo_root: Path, pattern: str) -> list[Path]:
    matches = [path for path in repo_root.glob(pattern) if path.is_file()]
    return sorted(matches)


def _capture_baseline(repo_root: Path, contract: dict[str, Any]) -> dict[str, Any]:
    baselines: dict[str, dict[str, str]] = {}
    for task in contract["tasks"]:
        for evidence in task.get("evidence", []):
            if evidence.get("kind") != "pathChanged":
                continue
            pattern = str(evidence.get("glob") or evidence.get("path") or "")
            key = stable_hash({"kind": "pathChanged", "pattern": pattern})
            snapshot: dict[str, str] = {}
            for path in _matching_paths(repo_root, pattern):
                snapshot[str(path.relative_to(repo_root))] = _hash_file(path)
            baselines[key] = snapshot
    return baselines


def _hashable_contract(payload: dict[str, Any]) -> dict[str, Any]:
    contract = deepcopy(payload)
    contract.pop("run_id", None)
    contract.pop("contract_hash", None)
    return contract


def _evaluate_evidence(
    repo_root: Path,
    task: dict[str, Any],
    verification: dict[str, Any],
    project_config: dict[str, Any],
) -> tuple[bool, list[str]]:
    details: list[str] = []
    evidence_items = list(task.get("evidence", []))
    if not evidence_items:
        return False, ["no deterministic evidence configured"]
    for evidence in evidence_items:
        kind = evidence.get("kind")
        if kind == "pathExists":
            rel = str(evidence.get("path", ""))
            if (repo_root / rel).exists():
                details.append(f"pathExists:{rel}=ok")
                continue
            details.append(f"pathExists:{rel}=missing")
            return False, details
        if kind == "pathChanged":
            pattern = str(evidence.get("glob") or evidence.get("path") or "")
            key = stable_hash({"kind": "pathChanged", "pattern": pattern})
            baseline = verification.get("baselines", {}).get(key, {})
            current: dict[str, str] = {}
            for path in _matching_paths(repo_root, pattern):
                current[str(path.relative_to(repo_root))] = _hash_file(path)
            if current != baseline:
                details.append(f"pathChanged:{pattern}=changed")
                continue
            details.append(f"pathChanged:{pattern}=unchanged")
            return False, details
        if kind == "commandRef":
            name = str(evidence.get("name", ""))
            argv = project_config.get("commands", {}).get(name)
            if not isinstance(argv, list):
                details.append(f"commandRef:{name}=unknown")
                return False, details
            result = run_command([str(item) for item in argv], cwd=repo_root)
            if result["passed"]:
                details.append(f"commandRef:{name}=ok")
                continue
            details.append(f"commandRef:{name}=failed")
            return False, details
        details.append(f"{kind}=unsupported")
        return False, details
    return True, details


class AutonomousLoopRuntime:
    def __init__(self, root: Path | None = None) -> None:
        self.paths = RuntimePaths(root.resolve() if root else RuntimePaths.from_env().root)
        self.store = RuntimeStore(self.paths)
        self.template_root = Path(__file__).resolve().parent / "resources" / "templates"

    def _logger(self, namespace: Namespace):
        return build_file_logger(f"autonomous_loop.{namespace.key}", self.paths.debug_log_path(namespace))

    def _touch_state(self, namespace: Namespace, state: RuntimeState, *, timestamp: str | None = None, event_type: str | None = None) -> str:
        now = timestamp or utc_now()
        state.updated_at = now
        state.heartbeat_at = now
        self.store.save_state(namespace, state)
        if event_type is not None:
            self.store.append_event(namespace, {"timestamp": now, "type": event_type})
        return now

    def _inspect_runtime_hygiene(
        self,
        repo_root: Path,
        *,
        stale_hours: int,
        retention_hours: int,
        preserve_session_id: str | None = None,
    ) -> dict[str, Any]:
        repo_hash = repo_hash_for(repo_root)
        self.paths.ensure_repo(repo_hash)
        now = datetime.now(timezone.utc)
        stale_cutoff = now - timedelta(hours=stale_hours)
        retention_cutoff = now - timedelta(hours=retention_hours)

        stale_active_sessions: list[dict[str, Any]] = []
        stale_paused_sessions: list[dict[str, Any]] = []
        stale_inactive_sessions: list[dict[str, Any]] = []
        stale_pending_requests: list[dict[str, Any]] = []
        stale_historical_requests: list[dict[str, Any]] = []

        sessions_dir = self.paths.sessions_dir(repo_hash)
        for session_path in sorted(sessions_dir.iterdir()) if sessions_dir.exists() else []:
            namespace = Namespace(repo_root=str(repo_root), repo_hash=repo_hash, session_id=session_path.name)
            state = self.store.load_state(namespace)
            if state is None:
                continue
            if preserve_session_id and state.session_id == preserve_session_id:
                continue
            activity_timestamp = _state_activity_timestamp(state)
            session_info = {
                "session_id": state.session_id,
                "state": state.state,
                "activity_at": activity_timestamp,
                "objective": state.objective,
            }
            if state.active and _timestamp_older_than(activity_timestamp, stale_cutoff):
                stale_active_sessions.append(session_info)
            elif state.paused and _timestamp_older_than(activity_timestamp, retention_cutoff):
                stale_paused_sessions.append(session_info)
            elif not state.active and not state.paused and _timestamp_older_than(activity_timestamp, retention_cutoff):
                stale_inactive_sessions.append(session_info)

        requests_dir = self.paths.pending_requests_dir(repo_hash)
        for request_path in sorted(requests_dir.glob("*.json")) if requests_dir.exists() else []:
            payload = read_json(request_path, None)
            if not isinstance(payload, dict):
                continue
            request = PendingRequest.from_dict(payload)
            request_info = {
                "request_id": request.request_id,
                "action": request.action,
                "status": request.status,
                "created_at": request.created_at,
            }
            archive_timestamp = request.applied_at or request.claimed_at or request.created_at
            if request.status == "pending" and _timestamp_older_than(request.created_at, stale_cutoff):
                stale_pending_requests.append(request_info)
            elif request.status != "pending" and _timestamp_older_than(archive_timestamp, retention_cutoff):
                stale_historical_requests.append(request_info)

        warnings: list[str] = []
        if stale_active_sessions:
            warnings.append(f"{len(stale_active_sessions)} stale active session(s) older than {stale_hours}h")
        if stale_paused_sessions:
            warnings.append(f"{len(stale_paused_sessions)} paused session(s) older than {retention_hours}h")
        if stale_inactive_sessions:
            warnings.append(f"{len(stale_inactive_sessions)} inactive session(s) older than {retention_hours}h")
        if stale_pending_requests:
            warnings.append(f"{len(stale_pending_requests)} unclaimed request(s) older than {stale_hours}h")
        if stale_historical_requests:
            warnings.append(f"{len(stale_historical_requests)} historical request(s) older than {retention_hours}h")

        return {
            "repo_root": str(repo_root),
            "stale_hours": stale_hours,
            "retention_hours": retention_hours,
            "warning_count": len(warnings),
            "warnings": warnings,
            "stale_active_sessions": stale_active_sessions,
            "stale_paused_sessions": stale_paused_sessions,
            "stale_inactive_sessions": stale_inactive_sessions,
            "stale_pending_requests": stale_pending_requests,
            "stale_historical_requests": stale_historical_requests,
        }

    def _cleanup_repo(
        self,
        repo_root: Path,
        *,
        stale_hours: int,
        retention_hours: int,
        preserve_session_id: str | None = None,
    ) -> dict[str, Any]:
        hygiene = self._inspect_runtime_hygiene(
            repo_root,
            stale_hours=stale_hours,
            retention_hours=retention_hours,
            preserve_session_id=preserve_session_id,
        )
        repo_hash = repo_hash_for(repo_root)
        archived_sessions: list[dict[str, Any]] = []
        archived_requests: list[dict[str, Any]] = []

        for session_info in hygiene["stale_active_sessions"] + hygiene["stale_paused_sessions"] + hygiene["stale_inactive_sessions"]:
            namespace = Namespace(repo_root=str(repo_root), repo_hash=repo_hash, session_id=session_info["session_id"])
            session_path = self.paths.session_dir(namespace)
            state = self.store.load_state(namespace)
            if state is None or not session_path.exists():
                continue
            if preserve_session_id and state.session_id == preserve_session_id:
                continue

            reason = ""
            if state.active:
                reason = f"stale active session older than {stale_hours}h"
            elif state.paused:
                reason = f"paused session older than {retention_hours}h"
            else:
                reason = f"inactive session older than {retention_hours}h"

            previous_state = state.state
            with file_lock(self.paths.lock_path(namespace)):
                state = self.store.load_state(namespace)
                if state is None:
                    continue
                if preserve_session_id and state.session_id == preserve_session_id:
                    continue
                previous_state = state.state
                if state.active or state.paused:
                    state.state = "stale"
                    state.active = False
                    state.paused = False
                    state.last_block_reason = reason
                    self._touch_state(namespace, state, event_type="cleanup-archived")

            self._clear_active_session(repo_hash, namespace.session_id)
            archived_to = _archive_move(session_path, self.paths.archived_sessions_dir(repo_hash) / session_path.name)
            archived_sessions.append(
                {
                    "session_id": namespace.session_id,
                    "previous_state": previous_state,
                    "archived_to": str(archived_to),
                    "reason": reason,
                }
            )

        requests_dir = self.paths.pending_requests_dir(repo_hash)
        for request_path in sorted(requests_dir.glob("*.json")) if requests_dir.exists() else []:
            payload = read_json(request_path, None)
            if not isinstance(payload, dict):
                continue
            request = PendingRequest.from_dict(payload)
            archive_reason: str | None = None
            if request.status == "pending":
                if any(item["request_id"] == request.request_id for item in hygiene["stale_pending_requests"]):
                    request.status = "expired"
                    archive_reason = f"unclaimed pending request older than {stale_hours}h"
            elif any(item["request_id"] == request.request_id for item in hygiene["stale_historical_requests"]):
                archive_reason = f"historical request older than {retention_hours}h"
            if archive_reason is None:
                continue

            archived_payload = request.to_dict()
            archived_payload["cleanup_reason"] = archive_reason
            archived_payload["archived_at"] = utc_now()
            archived_to = self.paths.archived_requests_dir(repo_hash) / request_path.name
            if archived_to.exists():
                archived_to = archived_to.with_name(f"{archived_to.stem}-{int(datetime.now(timezone.utc).timestamp())}{archived_to.suffix}")
            atomic_write_json(archived_to, archived_payload)
            request_path.unlink()
            archived_requests.append(
                {
                    "request_id": request.request_id,
                    "action": request.action,
                    "previous_status": payload.get("status"),
                    "archived_to": str(archived_to),
                    "reason": archive_reason,
                }
            )

        return {
            "repo_root": str(repo_root),
            "stale_hours": stale_hours,
            "retention_hours": retention_hours,
            "archived_sessions": archived_sessions,
            "archived_requests": archived_requests,
            "hygiene": hygiene,
        }

    def _activate(self, repo_root: Path, session_id: str, contract: dict[str, Any], project_config: dict[str, Any]) -> dict[str, Any]:
        namespace = self.paths.namespace(repo_root, session_id)
        self.paths.ensure_repo(namespace.repo_hash)
        self.store.write_project_cache(namespace.repo_hash, namespace.repo_root)
        normalized_contract = _normalize_contract(contract, project_config)
        contract_hash = stable_hash(normalized_contract)
        verification = {
            "version": "0.1",
            "contractHash": contract_hash,
            "gateProfile": normalized_contract["gateProfile"],
            "resolvedCommands": project_config.get("commands", {}),
            "gateProfiles": project_config.get("gateProfiles", {}),
            "baselines": _capture_baseline(repo_root, normalized_contract),
        }
        now = utc_now()
        state = RuntimeState(
            version="0.1",
            run_id=session_id,
            session_id=session_id,
            repo_root=str(repo_root),
            repo_hash=namespace.repo_hash,
            contract_id=str(normalized_contract["contractId"]),
            objective=str(normalized_contract["objective"]),
            state="active",
            active=True,
            paused=False,
            gate_profile=str(normalized_contract["gateProfile"]),
            fast_gate_profile=str(project_config.get("defaults", {}).get("fastGateProfile", "fast")),
            contract_hash=contract_hash,
            created_at=now,
            updated_at=now,
            heartbeat_at=now,
        )
        ledger = {
            "version": "0.1",
            "run_id": session_id,
            "session_id": session_id,
            "repo_root": str(repo_root),
            "repo_hash": namespace.repo_hash,
            "contract_hash": contract_hash,
            "iteration": 0,
            "state": "active",
            "last_block_reason": None,
            "last_failure_signature": None,
            "repeated_failure_count": 0,
            "last_gate_results": {},
            "events": [],
        }
        with file_lock(self.paths.lock_path(namespace)):
            contract_artifact = dict(normalized_contract)
            contract_artifact["run_id"] = session_id
            contract_artifact["contract_hash"] = contract_hash
            self.store.save_contract(namespace, contract_artifact)
            self.store.save_verification(namespace, verification)
            self.store.save_state(namespace, state)
            self.store.save_ledger(namespace, ledger)
            self.store.append_event(namespace, {"timestamp": now, "type": "activated", "session_id": session_id})
        self.store.write_active_session(namespace.repo_hash, session_id)
        self._logger(namespace).debug("activated contract_id=%s contract_hash=%s", normalized_contract["contractId"], contract_hash)
        return {
            "action": "enable",
            "run_id": session_id,
            "contract_hash": contract_hash,
            "repo_hash": namespace.repo_hash,
            "state_path": str(self.paths.state_path(namespace)),
            "contract_path": str(self.paths.contract_path(namespace)),
        }

    def _load_active_state(self, repo_root: Path, run_id: str | None = None) -> tuple[Namespace, RuntimeState] | tuple[None, None]:
        repo_hash = repo_hash_for(repo_root)
        session_dir = self.paths.sessions_dir(repo_hash)
        if not session_dir.exists():
            return None, None
        if run_id is not None:
            namespace = self.paths.namespace(repo_root, run_id)
            state = self.store.load_state(namespace)
            return (namespace, state) if state else (None, None)

        live_candidates: list[tuple[datetime, Namespace, RuntimeState]] = []
        for candidate in sorted(session_dir.iterdir()):
            namespace = Namespace(repo_root=str(repo_root), repo_hash=repo_hash, session_id=candidate.name)
            state = self.store.load_state(namespace)
            if state and state.active:
                activity = _parse_utc_timestamp(_state_activity_timestamp(state)) or datetime.fromtimestamp(0, tz=timezone.utc)
                live_candidates.append((activity, namespace, state))
        if live_candidates:
            _, namespace, state = max(live_candidates, key=lambda item: item[0])
            return namespace, state
        return None, None

    def enable(self, project_dir: str | Path, goal: str, enabled: bool = True, max_iterations: int = 12) -> dict[str, Any]:
        if not enabled:
            return {"action": "noop", "reason": "disabled"}
        repo_root = self.paths.resolve_repo_root(project_dir)
        project_config = self.store.load_project_config(repo_root)
        contract = _minimal_contract(goal, project_config, max_iterations)
        session_id = f"test-{secrets.token_hex(6)}"
        test_runtime = AutonomousLoopRuntime(root=Path(project_dir))
        return test_runtime._activate(repo_root, session_id, contract, project_config)

    def pause(self, project_dir: str | Path, run_id: str | None = None) -> dict[str, Any]:
        runtime = AutonomousLoopRuntime(root=Path(project_dir))
        repo_root = runtime.paths.resolve_repo_root(project_dir)
        namespace, state = runtime._load_active_state(repo_root, run_id)
        if state is None or namespace is None:
            return {"action": "noop", "reason": "no active run"}
        state.state = "paused"
        state.active = False
        state.paused = True
        state.paused_at = utc_now()
        runtime._touch_state(namespace, state, timestamp=state.paused_at, event_type="paused")
        return {"action": "allow", "paused": True, "run_id": state.run_id}

    def resume(self, project_dir: str | Path, run_id: str | None = None) -> dict[str, Any]:
        runtime = AutonomousLoopRuntime(root=Path(project_dir))
        repo_root = runtime.paths.resolve_repo_root(project_dir)
        namespace, state = runtime._load_active_state(repo_root, run_id)
        if state is None or namespace is None:
            namespace = runtime.paths.namespace(repo_root, run_id or "")
            state = runtime.store.load_state(namespace)
        if state is None or namespace is None:
            return {"action": "noop", "reason": "no run"}
        state.state = "active"
        state.active = True
        state.paused = False
        runtime._touch_state(namespace, state, event_type="resumed")
        return {"action": "allow", "paused": False, "run_id": state.run_id}

    def wrap_hook_result(self, exit_code: int, stdout: str = "", stderr: str = "") -> str:
        from .hooks import wrap_hook_result

        return wrap_hook_result(exit_code=exit_code, stdout=stdout, stderr=stderr)

    def _update_failure_counters(self, state: RuntimeState, contract: dict[str, Any], signature: str) -> tuple[bool, str | None]:
        state.iteration += 1
        if state.last_failure_signature == signature:
            state.repeated_failure_count += 1
        else:
            state.last_failure_signature = signature
            state.repeated_failure_count = 1
        limits = contract.get("limits", {})
        max_iterations = int(limits.get("maxStopIterations", 12))
        max_repeated = int(limits.get("maxRepeatedFailureSignature", 3))
        if state.iteration >= max_iterations:
            return True, f"autonomous-loop failed closed after {state.iteration} stop iterations"
        if state.repeated_failure_count >= max_repeated:
            return True, (
                "autonomous-loop failed closed after repeated identical failure signature "
                f"{state.last_failure_signature}"
            )
        return False, None

    def stop(
        self,
        project_dir: str | Path,
        run_id: str | None = None,
        contract_hash: str | None = None,
        tasks_complete: bool = False,
        final_gate_passed: bool = False,
        failure_signature: str | None = None,
    ) -> dict[str, Any]:
        runtime = AutonomousLoopRuntime(root=Path(project_dir))
        repo_root = runtime.paths.resolve_repo_root(project_dir)
        namespace, state = runtime._load_active_state(repo_root, run_id)
        if state is None or namespace is None:
            return {"action": "noop", "reason": "no active run"}
        contract = runtime.store.load_contract(namespace)
        if contract_hash and contract_hash != state.contract_hash:
            state.last_block_reason = "contract hash mismatch"
            runtime._touch_state(namespace, state)
            return {"action": "hard_stop", "reason": "contract hash mismatch"}
        if state.paused:
            return {"action": "noop", "reason": "paused"}
        if not tasks_complete:
            signature = failure_signature or "tasks-incomplete"
            hard_stop, reason = runtime._update_failure_counters(state, contract, signature)
            state.last_block_reason = "required tasks missing"
            runtime._touch_state(namespace, state)
            if hard_stop:
                state.state = "failed"
                state.active = False
                state.failed_at = utc_now()
                runtime._touch_state(namespace, state, timestamp=state.failed_at)
                return {"action": "hard_stop", "reason": reason}
            return {"action": "block", "reason": state.last_block_reason}
        if not final_gate_passed:
            signature = failure_signature or "final-gates-failed"
            hard_stop, reason = runtime._update_failure_counters(state, contract, signature)
            state.last_block_reason = "final gates failed"
            runtime._touch_state(namespace, state)
            if hard_stop:
                state.state = "failed"
                state.active = False
                state.failed_at = utc_now()
                runtime._touch_state(namespace, state, timestamp=state.failed_at)
                return {"action": "hard_stop", "reason": reason}
            return {"action": "block", "reason": state.last_block_reason}
        state.state = "released"
        state.active = False
        state.paused = False
        state.released_at = utc_now()
        runtime._touch_state(namespace, state, timestamp=state.released_at, event_type="released")
        return {"action": "allow", "released": True, "run_id": state.run_id}

    def _queue_request(self, action: str, cwd: str | Path, payload: dict[str, Any]) -> dict[str, Any]:
        repo_root = self.paths.resolve_repo_root(cwd)
        repo_hash = repo_hash_for(repo_root)
        request = PendingRequest(
            request_id=self.store.next_request_id(),
            action=action,
            nonce=secrets.token_hex(8),
            created_at=utc_now(),
            status="pending",
            payload=payload,
        )
        self.store.write_project_cache(repo_hash, str(repo_root))
        self.store.save_request(repo_hash, request)
        return {
            "action": action,
            "request_id": request.request_id,
            "nonce": request.nonce,
            "claim_token": f"AUTOLOOP_CLAIM:{request.nonce}",
            "repo_root": str(repo_root),
        }

    def _apply_direct_request(
        self,
        action: str,
        cwd: str | Path,
        payload: dict[str, Any],
        *,
        require_existing_state: bool,
    ) -> dict[str, Any] | None:
        session_id, source = _codex_session_binding()
        if session_id is None or source is None:
            return None
        repo_root = self.paths.resolve_repo_root(cwd)
        namespace = self.paths.namespace(repo_root, session_id)
        if action == "enable":
            self._cleanup_repo(
                repo_root,
                stale_hours=DEFAULT_STALE_HOURS,
                retention_hours=DEFAULT_RETENTION_HOURS,
                preserve_session_id=session_id,
            )
        if require_existing_state and self.store.load_state(namespace) is None:
            return None
        request = PendingRequest(
            request_id=self.store.next_request_id(),
            action=action,
            nonce=secrets.token_hex(8),
            created_at=utc_now(),
            status="pending",
            payload=payload,
        )
        self.store.write_project_cache(namespace.repo_hash, str(repo_root))
        self.store.save_request(namespace.repo_hash, request)
        state = self._apply_request(namespace, request, repo_root)
        result = {
            "action": action,
            "activation_mode": "direct-env",
            "repo_root": str(repo_root),
            "request_id": request.request_id,
            "session_id": session_id,
            "session_id_source": source,
        }
        if state is not None:
            result["run_id"] = state.run_id
            result["contract_hash"] = state.contract_hash
            result["state"] = state.state
        return result

    def request_enable(
        self,
        cwd: str | Path,
        objective: str,
        task_json: list[dict[str, Any]] | None = None,
        gate_profile: str | None = None,
        max_stop_iterations: int | None = None,
    ) -> dict[str, Any]:
        repo_root = self.paths.resolve_repo_root(cwd)
        project_config = self.store.load_project_config(repo_root)
        contract = _minimal_contract(objective, project_config, max_stop_iterations or _default_limits(project_config)["maxStopIterations"])
        if task_json:
            contract["tasks"] = task_json
        if gate_profile:
            contract["gateProfile"] = gate_profile
        direct_result = self._apply_direct_request(
            "enable",
            repo_root,
            {"contract": _normalize_contract(contract, project_config)},
            require_existing_state=False,
        )
        if direct_result is not None:
            return direct_result
        return self._queue_request("enable", repo_root, {"contract": _normalize_contract(contract, project_config)})

    def request_action(self, action: str, cwd: str | Path, reason: str | None = None) -> dict[str, Any]:
        direct_result = self._apply_direct_request(
            action,
            cwd,
            {"reason": reason},
            require_existing_state=True,
        )
        if direct_result is not None:
            return direct_result
        return self._queue_request(action, cwd, {"reason": reason})

    def _apply_request(self, namespace: Namespace, request: PendingRequest, repo_root: Path) -> RuntimeState | None:
        project_config = self.store.load_project_config(repo_root)
        logger = self._logger(namespace)
        request.status = "applied"
        request.claimed_by_session = namespace.session_id
        request.claimed_at = utc_now()
        request.applied_at = request.claimed_at
        if request.action == "enable":
            result = self._activate(repo_root, namespace.session_id, request.payload["contract"], project_config)
            self.store.save_request(namespace.repo_hash, request)
            logger.debug("applied enable request_id=%s", request.request_id)
            return self.store.load_state(namespace)
        state = self.store.load_state(namespace)
        if state is None:
            self.store.save_request(namespace.repo_hash, request)
            return None
        if request.action == "pause":
            state.state = "paused"
            state.active = False
            state.paused = True
            state.paused_at = utc_now()
        elif request.action == "resume":
            state.state = "active"
            state.active = True
            state.paused = False
        elif request.action == "disable":
            state.state = "disabled"
            state.active = False
            state.paused = False
        elif request.action == "release":
            state.state = "released"
            state.active = False
            state.released_at = utc_now()
        if request.action in ("disable", "release"):
            self._clear_active_session(namespace.repo_hash, namespace.session_id)
        self._touch_state(namespace, state)
        self.store.save_request(namespace.repo_hash, request)
        self.store.append_event(namespace, {"timestamp": utc_now(), "type": f"request-{request.action}"})
        logger.debug("applied request action=%s request_id=%s", request.action, request.request_id)
        return state

    def handle_session_start_payload(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        repo_root = self.paths.resolve_repo_root(payload["cwd"])
        namespace = self.paths.namespace(repo_root, str(payload["session_id"]))
        self._cleanup_repo(
            repo_root,
            stale_hours=DEFAULT_STALE_HOURS,
            retention_hours=DEFAULT_RETENTION_HOURS,
            preserve_session_id=namespace.session_id,
        )
        state = self.store.load_state(namespace)
        if state is None or state.state not in {"active", "paused"}:
            return None
        self._touch_state(namespace, state, event_type="heartbeat")
        contract = self.store.load_contract(namespace) or {}
        outstanding = ", ".join(state.outstanding_task_ids) or "none recorded yet"
        gates = ", ".join(state.last_gate_failures) or "none recorded yet"
        policy = contract.get("policy", {}).get("semanticReview", "advisory-after-green")
        message = (
            f"autonomous-loop {state.state} for contract {state.contract_id}. "
            f"Objective: {state.objective}. Outstanding tasks: {outstanding}. "
            f"Last failing gates: {gates}. Policy: deterministic contract completion plus trusted gates; "
            f"semantic review is {policy}."
        )
        from .hooks import session_start_context

        return session_start_context(message)

    def _clear_active_session(self, repo_hash: str, session_id: str) -> None:
        recorded = self.store.read_active_session(repo_hash)
        if recorded == session_id:
            try:
                self.paths.active_session_path(repo_hash).unlink(missing_ok=True)
            except OSError:
                pass

    def handle_stop_payload(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        repo_root = self.paths.resolve_repo_root(payload["cwd"])
        namespace = self.paths.namespace(repo_root, str(payload["session_id"]))
        nonce = parse_claim_nonce(payload.get("last_assistant_message"))
        if nonce:
            request = self.store.find_pending_request_by_nonce(namespace.repo_hash, nonce)
            if request is not None:
                self._apply_request(namespace, request, repo_root)
        active_session = self.store.read_active_session(namespace.repo_hash)
        if active_session is not None and active_session != namespace.session_id:
            return None
        state = self.store.load_state(namespace)
        if state is None:
            return None
        if state.state in {"disabled", "released"} or state.paused:
            return None
        logger = self._logger(namespace)
        with file_lock(self.paths.lock_path(namespace)):
            contract = self.store.load_contract(namespace)
            verification = self.store.load_verification(namespace)
            ledger = self.store.load_ledger(namespace) or {}
            state = self.store.load_state(namespace)
            if state is None:
                return None
            state.heartbeat_at = utc_now()
            if contract is None or verification is None:
                state.state = "failed"
                state.active = False
                state.failed_at = utc_now()
                state.updated_at = state.failed_at
                self.store.save_state(namespace, state)
                self._clear_active_session(namespace.repo_hash, namespace.session_id)
                return stop_hard_stop("autonomous-loop failed closed: unreadable contract or verification state")
            contract_hash = stable_hash(_hashable_contract(contract))
            if contract_hash != state.contract_hash or verification.get("contractHash") != state.contract_hash:
                state.state = "failed"
                state.active = False
                state.failed_at = utc_now()
                state.updated_at = state.failed_at
                self.store.save_state(namespace, state)
                self._clear_active_session(namespace.repo_hash, namespace.session_id)
                return stop_hard_stop("autonomous-loop failed closed: contract hash mismatch")
            outstanding: list[str] = []
            task_details: list[str] = []
            for task in contract.get("tasks", []):
                if not task.get("required", True):
                    continue
                complete, details = _evaluate_evidence(repo_root, task, verification, self.store.load_project_config(repo_root))
                if not complete:
                    outstanding.append(task["id"])
                    task_details.append(f"{task['id']} ({task['title']}): " + "; ".join(details))
            state.outstanding_task_ids = outstanding
            project_config = self.store.load_project_config(repo_root)
            if outstanding:
                fast_profile = state.fast_gate_profile or project_config.get("defaults", {}).get("fastGateProfile", "fast")
                gate_run = run_gate_profile(fast_profile, project_config, repo_root)
                state.last_gate_failures = list(gate_run["failures"])
                reason = f"Outstanding tasks: {', '.join(task_details)}"
                if gate_run["failures"]:
                    reason += f". Fast gates failing: {', '.join(gate_run['failures'])}"
                signature = stable_hash({"tasks": outstanding, "gates": gate_run["failures"]})
                hard_stop, stop_reason = self._update_failure_counters(state, contract, signature)
                state.last_block_reason = reason
                state.updated_at = utc_now()
                ledger["iteration"] = state.iteration
                ledger["last_block_reason"] = reason
                ledger["last_gate_results"] = gate_run["results"]
                self.store.save_state(namespace, state)
                self.store.save_ledger(namespace, ledger)
                self.store.append_event(namespace, {"timestamp": utc_now(), "type": "blocked", "reason": reason})
                logger.debug("blocked outstanding=%s", outstanding)
                if hard_stop:
                    state.state = "failed"
                    state.active = False
                    state.failed_at = utc_now()
                    state.updated_at = state.failed_at
                    self.store.save_state(namespace, state)
                    self._clear_active_session(namespace.repo_hash, namespace.session_id)
                    return stop_hard_stop(stop_reason or "autonomous-loop failed closed")
                return stop_block(reason)
            final_profile = state.gate_profile or project_config.get("defaults", {}).get("finalGateProfile", "final")
            final_run = run_gate_profile(final_profile, project_config, repo_root)
            state.last_gate_failures = list(final_run["failures"])
            if not final_run["passed"]:
                reason = f"Final gates failed: {', '.join(final_run['failures'])}"
                signature = stable_hash({"final_failures": final_run["failures"]})
                hard_stop, stop_reason = self._update_failure_counters(state, contract, signature)
                state.last_block_reason = reason
                state.updated_at = utc_now()
                ledger["iteration"] = state.iteration
                ledger["last_block_reason"] = reason
                ledger["last_gate_results"] = final_run["results"]
                self.store.save_state(namespace, state)
                self.store.save_ledger(namespace, ledger)
                self.store.append_event(namespace, {"timestamp": utc_now(), "type": "blocked-final-gates", "reason": reason})
                if hard_stop:
                    state.state = "failed"
                    state.active = False
                    state.failed_at = utc_now()
                    state.updated_at = state.failed_at
                    self.store.save_state(namespace, state)
                    self._clear_active_session(namespace.repo_hash, namespace.session_id)
                    return stop_hard_stop(stop_reason or "autonomous-loop failed closed")
                return stop_block(reason)
            state.state = "released"
            state.active = False
            state.paused = False
            state.released_at = utc_now()
            state.updated_at = state.released_at
            ledger["state"] = "released"
            ledger["released_at"] = state.released_at
            ledger["last_gate_results"] = final_run["results"]
            self.store.save_state(namespace, state)
            self.store.save_ledger(namespace, ledger)
            self.store.append_event(namespace, {"timestamp": state.released_at, "type": "released"})
            self._clear_active_session(namespace.repo_hash, namespace.session_id)
            logger.debug("released run_id=%s", state.run_id)
            return None

    def bootstrap(self, *, force: bool = False) -> dict[str, Any]:
        command_path, cli_error = resolve_cli_path()
        if command_path is None:
            return {
                "ok": False,
                "error_code": "cli_not_found",
                "message": cli_error or "autonomous-loop was not found on PATH",
            }

        machine_config = build_machine_config(command_path, codex_home=self.paths.codex_home())
        hook_commands = machine_config["hook_commands"]

        written: list[str] = []
        hooks_path = self.store.write_global_hooks(hook_commands, force=force)
        if hooks_path is not None:
            written.append(hooks_path)

        skill_path = self.store.install_global_skill(self.template_root, force=force)
        if skill_path is not None:
            written.append(skill_path)

        machine_path = self.store.save_machine_config(machine_config)
        written.append(machine_path)

        return {
            "ok": True,
            "command_mode": machine_config["command_mode"],
            "command_path": machine_config["command_path"],
            "hook_commands": machine_config["hook_commands"],
            "machine_config_path": machine_path,
            "global_hooks_path": hooks_path or str(self.paths.codex_home_hooks_path()),
            "global_skill_path": skill_path or str(self.paths.global_skill_path()),
            "written": written,
        }

    def doctor(self, cwd: str | Path | None = None) -> dict[str, Any]:
        checks: dict[str, dict[str, Any]] = {}

        command_path, cli_error = resolve_cli_path()
        if command_path is None:
            checks["cli_on_path"] = {"ok": False, "reason": cli_error}
        else:
            checks["cli_on_path"] = {"ok": True, "path": command_path}

        machine = self.store.load_machine_config()
        machine_ok, machine_error = validate_machine_config(machine)
        if not machine_ok:
            checks["machine_config"] = {
                "ok": False,
                "reason": machine_error,
                "path": str(self.paths.machine_config_path()),
            }
        else:
            if machine is None:
                return {"ok": False, "error_code": "internal_error", "message": "machine config unexpectedly None after validation"}
            command_file = Path(machine["command_path"])
            if not command_file.is_absolute():
                checks["machine_config"] = {"ok": False, "reason": "machine config command_path must be absolute"}
            elif not command_file.exists():
                checks["machine_config"] = {
                    "ok": False,
                    "reason": f"machine config command_path is missing: {command_file}",
                }
            elif not os.access(command_file, os.X_OK):
                checks["machine_config"] = {
                    "ok": False,
                    "reason": f"machine config command_path is not executable: {command_file}",
                }
            else:
                checks["machine_config"] = {
                    "ok": True,
                    "path": str(self.paths.machine_config_path()),
                    "command_path": machine["command_path"],
                    "command_mode": machine["command_mode"],
                }
                if command_path is not None and not _paths_equivalent(command_path, machine["command_path"]):
                    checks["cli_on_path"] = {
                        "ok": False,
                        "path": command_path,
                        "reason": (
                            "`autonomous-loop` on PATH does not match the machine bootstrap command_path"
                        ),
                        "expected_path": machine["command_path"],
                        "remediation": (
                            "Update PATH so `autonomous-loop` resolves to the bootstrapped launcher, "
                            "or rerun `autonomous-loop bootstrap --force` after installing the intended CLI."
                        ),
                    }
                if "codex_version" in machine:
                    current_codex = detect_codex_version(self.paths.codex_home())
                    recorded_codex = machine["codex_version"]
                    if current_codex is not None and current_codex != recorded_codex:
                        checks["codex_version_drift"] = {
                            "ok": False,
                            "reason": (
                                f"Codex version changed from {recorded_codex!r} "
                                f"to {current_codex!r} since last bootstrap"
                            ),
                            "recorded_version": recorded_codex,
                            "current_version": current_codex,
                            "remediation": "Run 'autonomous-loop bootstrap --force' to update machine config.",
                        }
                    else:
                        checks["codex_version_drift"] = {"ok": True, "codex_version": recorded_codex}

        hooks_path = self.paths.codex_home_hooks_path()
        if not hooks_path.is_file():
            checks["global_hooks"] = {"ok": False, "reason": f"missing hooks.json at {hooks_path}"}
        else:
            hooks_json = read_json(hooks_path, None)
            if machine_ok and machine is not None:
                hooks_ok, hooks_reason = _check_hooks_match(hooks_json, machine)
                if not hooks_ok:
                    checks["global_hooks"] = {
                        "ok": False,
                        "reason": f"global hooks {hooks_reason}",
                        "path": str(hooks_path),
                    }
                else:
                    checks["global_hooks"] = {"ok": True, "path": str(hooks_path)}
            else:
                checks["global_hooks"] = {"ok": True, "path": str(hooks_path)}

        skill_path = self.paths.global_skill_path()
        if not skill_path.is_file():
            checks["global_skill"] = {"ok": False, "reason": f"missing skill at {skill_path}"}
        else:
            checks["global_skill"] = {"ok": True, "path": str(skill_path)}

        if cwd is not None:
            repo_root = self.paths.resolve_repo_root(cwd)
            config_path = repo_root / ".codex" / "autoloop.project.json"
            hooks_repo_path = repo_root / ".codex" / "hooks.json"
            skill_repo_path = repo_root / ".agents" / "skills" / "autonomous-loop" / "SKILL.md"
            if not config_path.is_file():
                checks["repo_install"] = {
                    "ok": False,
                    "reason": f"missing .codex/autoloop.project.json at {config_path}",
                    "repo_root": str(repo_root),
                }
            elif not hooks_repo_path.is_file():
                checks["repo_install"] = {
                    "ok": False,
                    "reason": f"missing .codex/hooks.json at {hooks_repo_path}",
                    "repo_root": str(repo_root),
                }
            elif not skill_repo_path.is_file():
                checks["repo_install"] = {
                    "ok": False,
                    "reason": f"missing repo-local skill at {skill_repo_path}",
                    "repo_root": str(repo_root),
                }
            else:
                hooks_json = read_json(hooks_repo_path, None)
                if machine_ok and machine is not None:
                    hooks_ok, hooks_reason = _check_hooks_match(hooks_json, machine)
                    if not hooks_ok:
                        checks["repo_install"] = {
                            "ok": False,
                            "reason": f"repo hooks {hooks_reason}",
                            "repo_root": str(repo_root),
                            "remediation": f"Rerun `autonomous-loop install-repo --repo {repo_root} --force` to update hooks.",
                        }
                    else:
                        checks["repo_install"] = {"ok": True, "repo_root": str(repo_root)}
                else:
                    checks["repo_install"] = {"ok": True, "repo_root": str(repo_root)}
            checks["runtime_hygiene"] = {
                "ok": True,
                **self._inspect_runtime_hygiene(
                    repo_root,
                    stale_hours=DEFAULT_STALE_HOURS,
                    retention_hours=DEFAULT_RETENTION_HOURS,
                ),
            }

        repos_dir = self.paths.root / "repos"
        if repos_dir.is_dir():
            inode_to_hashes: dict[int, list[str]] = {}
            for hash_dir in repos_dir.iterdir():
                if not hash_dir.is_dir():
                    continue
                cache = read_json(self.paths.project_cache_path(hash_dir.name), None)
                if not isinstance(cache, dict):
                    continue
                root_path_str = cache.get("repo_root")
                if not root_path_str:
                    continue
                try:
                    inode = Path(root_path_str).stat().st_ino
                except OSError:
                    continue
                inode_to_hashes.setdefault(inode, []).append(hash_dir.name)
            duplicates = {str(k): v for k, v in inode_to_hashes.items() if len(v) > 1}
            if duplicates:
                checks["duplicate_repo_hashes"] = {
                    "ok": False,
                    "reason": (
                        f"{len(duplicates)} repo(s) with duplicate hash directories "
                        "(case-sensitive path collision on a case-insensitive filesystem). "
                        "Run 'autonomous-loop cleanup' to archive stale entries."
                    ),
                    "duplicates": duplicates,
                }

        ok = all(bool(item.get("ok")) for item in checks.values())
        payload: dict[str, Any] = {"ok": ok, "checks": checks}
        if cwd is not None:
            payload["cwd"] = str(Path(cwd))
        return payload

    def cleanup(
        self,
        cwd: str | Path,
        *,
        stale_hours: int = DEFAULT_STALE_HOURS,
        retention_hours: int = DEFAULT_RETENTION_HOURS,
    ) -> dict[str, Any]:
        if stale_hours < 1:
            return {"ok": False, "error_code": "invalid_stale_hours", "message": "stale_hours must be at least 1"}
        if retention_hours < stale_hours:
            return {
                "ok": False,
                "error_code": "invalid_retention_hours",
                "message": "retention_hours must be greater than or equal to stale_hours",
            }

        repo_root = self.paths.resolve_repo_root(cwd)
        current_session_id, _ = _codex_session_binding()
        result = self._cleanup_repo(
            repo_root,
            stale_hours=stale_hours,
            retention_hours=retention_hours,
            preserve_session_id=current_session_id,
        )
        result["ok"] = True
        return result

    def status(self, cwd: str | Path, session_id: str | None = None) -> dict[str, Any]:
        repo_root = self.paths.resolve_repo_root(cwd)
        repo_hash = repo_hash_for(repo_root)
        sessions: list[dict[str, Any]] = []
        for session_path in sorted(self.paths.sessions_dir(repo_hash).glob("*")) if self.paths.sessions_dir(repo_hash).exists() else []:
            namespace = Namespace(repo_root=str(repo_root), repo_hash=repo_hash, session_id=session_path.name)
            state = self.store.load_state(namespace)
            if state:
                sessions.append(state.to_dict())
        sessions.sort(
            key=lambda item: _parse_utc_timestamp(str(item.get("heartbeat_at") or item.get("updated_at") or item.get("created_at"))) or datetime.fromtimestamp(0, tz=timezone.utc),
            reverse=True,
        )
        requests = [request.to_dict() for request in self.store.list_requests(repo_hash)]
        requests.sort(
            key=lambda item: _parse_utc_timestamp(str(item.get("created_at") or "")) or datetime.fromtimestamp(0, tz=timezone.utc),
            reverse=True,
        )
        if session_id:
            namespace = self.paths.namespace(repo_root, session_id)
            state = self.store.load_state(namespace)
            sessions = [state.to_dict()] if state else []
        archived_sessions_count = sum(1 for _ in self.paths.archived_sessions_dir(repo_hash).glob("*")) if self.paths.archived_sessions_dir(repo_hash).exists() else 0
        archived_requests_count = sum(1 for _ in self.paths.archived_requests_dir(repo_hash).glob("*.json")) if self.paths.archived_requests_dir(repo_hash).exists() else 0
        return {
            "repo_root": str(repo_root),
            "repo_hash": repo_hash,
            "sessions": sessions,
            "pending_requests": requests,
            "archived_counts": {
                "sessions": archived_sessions_count,
                "requests": archived_requests_count,
            },
            "hygiene": self._inspect_runtime_hygiene(
                repo_root,
                stale_hours=DEFAULT_STALE_HOURS,
                retention_hours=DEFAULT_RETENTION_HOURS,
                preserve_session_id=session_id,
            ),
        }

    def install_repo(
        self,
        repo_root: str | Path,
        force: bool = False,
        package_manager: str | None = None,
        prefer_scripts: list[str] | None = None,
    ) -> dict[str, Any]:
        repo = self.paths.resolve_repo_root(repo_root)
        machine = self.store.load_machine_config()
        machine_ok, machine_error = validate_machine_config(machine)
        if not machine_ok:
            return {
                "ok": False,
                "error_code": "missing_machine_bootstrap",
                "repo_root": str(repo),
                "message": "Run `autonomous-loop bootstrap` before `install-repo`.",
                "remediation": [
                    "Run `autonomous-loop bootstrap`",
                    f"Then rerun `autonomous-loop install-repo --repo {repo}`",
                ],
                "evidence": {
                    "machine_config_path": str(self.paths.machine_config_path()),
                    "reason": machine_error,
                },
            }
        if machine is None:
            return {"ok": False, "error_code": "internal_error", "message": "machine config unexpectedly None after validation"}

        try:
            prepared = inspect_repo(
                repo,
                package_manager_override=package_manager,
                prefer_scripts=prefer_scripts,
            )
        except InstallRepoFailure as exc:
            return exc.to_payload(repo)

        copied: list[str] = []
        warnings = list(prepared["warnings"])
        config_path = self.store.write_generated_project_config(
            repo,
            prepared["project_config"],
            force=force,
        )
        if config_path is None:
            warnings.append(
                "Existing .codex/autoloop.project.json was preserved; rerun with --force to overwrite it."
            )
        else:
            copied.append(config_path)
        hooks_path = self.store.write_repo_hooks(repo, machine["hook_commands"], force=force)
        if hooks_path is not None:
            copied.append(hooks_path)
        skill_path = self.store.install_repo_skill_template(self.template_root, repo, force=force)
        if skill_path is not None:
            copied.append(skill_path)
        return {
            "ok": True,
            "repo_root": str(repo),
            "package_manager_detected": prepared["package_manager_detected"],
            "scripts_detected": prepared["scripts_detected"],
            "commands_generated": prepared["commands_generated"],
            "gate_profiles_generated": prepared["gate_profiles_generated"],
            "copied": copied,
            "warnings": warnings,
        }


AutonomousLoopController = AutonomousLoopRuntime
