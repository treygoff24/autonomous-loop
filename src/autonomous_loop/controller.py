from __future__ import annotations

import secrets
from copy import deepcopy
from pathlib import Path
from typing import Any

from .gates import run_command, run_gate_profile
from .hashes import stable_hash
from .hooks import parse_claim_nonce, stop_block, stop_hard_stop
from .locks import file_lock
from .logging_utils import build_file_logger
from .models import Namespace, PendingRequest, RuntimeState, utc_now
from .paths import RuntimePaths, hash_text
from .storage import RuntimeStore


def _default_limits(project_config: dict[str, Any]) -> dict[str, int]:
    defaults = project_config.get("defaults", {})
    return {
        "maxStopIterations": int(defaults.get("maxStopIterations", 12)),
        "maxRepeatedFailureSignature": int(defaults.get("maxRepeatedFailureSignature", 3)),
    }


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
        repo_hash = hash_text(str(repo_root.resolve()))
        session_dir = self.paths.sessions_dir(repo_hash)
        if not session_dir.exists():
            return None, None
        for candidate in sorted(session_dir.iterdir()):
            namespace = Namespace(repo_root=str(repo_root), repo_hash=repo_hash, session_id=candidate.name if run_id is None else run_id)
            if run_id is not None:
                namespace = self.paths.namespace(repo_root, run_id)
                state = self.store.load_state(namespace)
                return (namespace, state) if state else (None, None)
            state = self.store.load_state(namespace)
            if state and state.active:
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
        state.updated_at = state.paused_at
        runtime.store.save_state(namespace, state)
        runtime.store.append_event(namespace, {"timestamp": state.paused_at, "type": "paused"})
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
        state.updated_at = utc_now()
        runtime.store.save_state(namespace, state)
        runtime.store.append_event(namespace, {"timestamp": state.updated_at, "type": "resumed"})
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
            state.updated_at = utc_now()
            runtime.store.save_state(namespace, state)
            return {"action": "hard_stop", "reason": "contract hash mismatch"}
        if state.paused:
            return {"action": "noop", "reason": "paused"}
        if not tasks_complete:
            signature = failure_signature or "tasks-incomplete"
            hard_stop, reason = runtime._update_failure_counters(state, contract, signature)
            state.last_block_reason = "required tasks missing"
            state.updated_at = utc_now()
            runtime.store.save_state(namespace, state)
            if hard_stop:
                state.state = "failed"
                state.active = False
                state.failed_at = utc_now()
                runtime.store.save_state(namespace, state)
                return {"action": "hard_stop", "reason": reason}
            return {"action": "block", "reason": state.last_block_reason}
        if not final_gate_passed:
            signature = failure_signature or "final-gates-failed"
            hard_stop, reason = runtime._update_failure_counters(state, contract, signature)
            state.last_block_reason = "final gates failed"
            state.updated_at = utc_now()
            runtime.store.save_state(namespace, state)
            if hard_stop:
                state.state = "failed"
                state.active = False
                state.failed_at = utc_now()
                runtime.store.save_state(namespace, state)
                return {"action": "hard_stop", "reason": reason}
            return {"action": "block", "reason": state.last_block_reason}
        state.state = "released"
        state.active = False
        state.paused = False
        state.released_at = utc_now()
        state.updated_at = state.released_at
        runtime.store.save_state(namespace, state)
        runtime.store.append_event(namespace, {"timestamp": state.released_at, "type": "released"})
        return {"action": "allow", "released": True, "run_id": state.run_id}

    def _queue_request(self, action: str, cwd: str | Path, payload: dict[str, Any]) -> dict[str, Any]:
        repo_root = self.paths.resolve_repo_root(cwd)
        repo_hash = hash_text(str(repo_root))
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
        return self._queue_request("enable", repo_root, {"contract": _normalize_contract(contract, project_config)})

    def request_action(self, action: str, cwd: str | Path, reason: str | None = None) -> dict[str, Any]:
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
        state.updated_at = utc_now()
        self.store.save_state(namespace, state)
        self.store.save_request(namespace.repo_hash, request)
        self.store.append_event(namespace, {"timestamp": utc_now(), "type": f"request-{request.action}"})
        logger.debug("applied request action=%s request_id=%s", request.action, request.request_id)
        return state

    def handle_session_start_payload(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        repo_root = self.paths.resolve_repo_root(payload["cwd"])
        namespace = self.paths.namespace(repo_root, str(payload["session_id"]))
        state = self.store.load_state(namespace)
        if state is None or state.state not in {"active", "paused"}:
            return None
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

    def handle_stop_payload(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        repo_root = self.paths.resolve_repo_root(payload["cwd"])
        namespace = self.paths.namespace(repo_root, str(payload["session_id"]))
        nonce = parse_claim_nonce(payload.get("last_assistant_message"))
        if nonce:
            request = self.store.find_pending_request_by_nonce(namespace.repo_hash, nonce)
            if request is not None:
                self._apply_request(namespace, request, repo_root)
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
            if contract is None or verification is None:
                state.state = "failed"
                state.active = False
                state.failed_at = utc_now()
                state.updated_at = state.failed_at
                self.store.save_state(namespace, state)
                return stop_hard_stop("autonomous-loop failed closed: unreadable contract or verification state")
            contract_hash = stable_hash(_hashable_contract(contract))
            if contract_hash != state.contract_hash or verification.get("contractHash") != state.contract_hash:
                state.state = "failed"
                state.active = False
                state.failed_at = utc_now()
                state.updated_at = state.failed_at
                self.store.save_state(namespace, state)
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
            logger.debug("released run_id=%s", state.run_id)
            return None

    def status(self, cwd: str | Path, session_id: str | None = None) -> dict[str, Any]:
        repo_root = self.paths.resolve_repo_root(cwd)
        repo_hash = hash_text(str(repo_root))
        sessions: list[dict[str, Any]] = []
        for session_path in sorted(self.paths.sessions_dir(repo_hash).glob("*")) if self.paths.sessions_dir(repo_hash).exists() else []:
            namespace = Namespace(repo_root=str(repo_root), repo_hash=repo_hash, session_id=session_path.name)
            state = self.store.load_state(namespace)
            if state:
                sessions.append(state.to_dict())
        requests = [request.to_dict() for request in self.store.list_requests(repo_hash)]
        if session_id:
            namespace = self.paths.namespace(repo_root, session_id)
            state = self.store.load_state(namespace)
            sessions = [state.to_dict()] if state else []
        return {"repo_root": str(repo_root), "repo_hash": repo_hash, "sessions": sessions, "pending_requests": requests}

    def install_repo(self, repo_root: str | Path, force: bool = False) -> dict[str, Any]:
        repo = self.paths.resolve_repo_root(repo_root)
        copied = self.store.install_repo_templates(self.template_root, repo, force=force)
        return {"repo_root": str(repo), "copied": copied}


AutonomousLoopController = AutonomousLoopRuntime
