from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path
from typing import Any

from .bootstrap import build_hooks_payload
from .models import PendingRequest, RuntimeState
from .paths import RuntimePaths


DEFAULT_PROJECT_CONFIG: dict[str, Any] = {
    "version": "0.1",
    "commands": {},
    "gateProfiles": {"fast": [], "default": [], "final": []},
    "defaults": {
        "gateProfile": "default",
        "fastGateProfile": "fast",
        "finalGateProfile": "final",
        "maxStopIterations": 12,
        "maxRepeatedFailureSignature": 3,
    },
}


def atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


class RuntimeStore:
    def __init__(self, paths: RuntimePaths) -> None:
        self.paths = paths

    def next_request_id(self) -> str:
        return uuid.uuid4().hex

    def write_active_session(self, repo_hash: str, session_id: str) -> None:
        atomic_write_json(self.paths.active_session_path(repo_hash), {"session_id": session_id})

    def read_active_session(self, repo_hash: str) -> str | None:
        payload = read_json(self.paths.active_session_path(repo_hash), None)
        if not isinstance(payload, dict):
            return None
        value = payload.get("session_id")
        return str(value) if value else None

    def write_project_cache(self, repo_hash: str, repo_root: str) -> None:
        self.paths.ensure_repo(repo_hash)
        atomic_write_json(self.paths.project_cache_path(repo_hash), {"repo_root": repo_root})

    def load_project_config(self, repo_root: Path) -> dict[str, Any]:
        config_path = repo_root / ".codex" / "autoloop.project.json"
        payload = read_json(config_path, None)
        if payload is None:
            return json.loads(json.dumps(DEFAULT_PROJECT_CONFIG))
        merged = json.loads(json.dumps(DEFAULT_PROJECT_CONFIG))
        merged["commands"].update(payload.get("commands", {}))
        merged["gateProfiles"].update(payload.get("gateProfiles", {}))
        merged["defaults"].update(payload.get("defaults", {}))
        merged["semanticReview"] = payload.get("semanticReview", "advisory-after-green")
        return merged

    def save_request(self, repo_hash: str, request: PendingRequest) -> Path:
        self.paths.ensure_repo(repo_hash)
        path = self.paths.pending_request_path(repo_hash, request.request_id)
        atomic_write_json(path, request.to_dict())
        return path

    def load_request(self, repo_hash: str, request_id: str) -> PendingRequest:
        return PendingRequest.from_dict(read_json(self.paths.pending_request_path(repo_hash, request_id)))

    def list_requests(self, repo_hash: str) -> list[PendingRequest]:
        self.paths.ensure_repo(repo_hash)
        items: list[PendingRequest] = []
        for path in sorted(self.paths.pending_requests_dir(repo_hash).glob("*.json")):
            items.append(PendingRequest.from_dict(read_json(path)))
        return items

    def find_pending_request_by_nonce(self, repo_hash: str, nonce: str) -> PendingRequest | None:
        for request in self.list_requests(repo_hash):
            if request.nonce == nonce and request.status == "pending":
                return request
        return None

    def save_state(self, namespace, state: RuntimeState) -> None:
        self.paths.ensure_session(namespace)
        atomic_write_json(self.paths.state_path(namespace), state.to_dict())

    def load_state(self, namespace) -> RuntimeState | None:
        payload = read_json(self.paths.state_path(namespace), None)
        if payload is None:
            return None
        return RuntimeState.from_dict(payload)

    def save_contract(self, namespace, payload: dict[str, Any]) -> None:
        self.paths.ensure_session(namespace)
        atomic_write_json(self.paths.contract_path(namespace), payload)

    def load_contract(self, namespace) -> dict[str, Any] | None:
        return read_json(self.paths.contract_path(namespace), None)

    def save_verification(self, namespace, payload: dict[str, Any]) -> None:
        self.paths.ensure_session(namespace)
        atomic_write_json(self.paths.verification_path(namespace), payload)

    def load_verification(self, namespace) -> dict[str, Any] | None:
        return read_json(self.paths.verification_path(namespace), None)

    def save_ledger(self, namespace, payload: dict[str, Any]) -> None:
        self.paths.ensure_session(namespace)
        atomic_write_json(self.paths.ledger_path(namespace), payload)

    def load_ledger(self, namespace) -> dict[str, Any] | None:
        return read_json(self.paths.ledger_path(namespace), None)

    def append_event(self, namespace, payload: dict[str, Any]) -> None:
        append_jsonl(self.paths.events_log_path(namespace), payload)

    def write_generated_project_config(self, repo_root: Path, payload: dict[str, Any], force: bool = False) -> str | None:
        path = repo_root / ".codex" / "autoloop.project.json"
        if path.exists() and not force:
            return None
        atomic_write_json(path, payload)
        return str(path)

    def save_machine_config(self, payload: dict[str, Any]) -> str:
        path = self.paths.machine_config_path()
        atomic_write_json(path, payload)
        return str(path)

    def load_machine_config(self) -> dict[str, Any] | None:
        payload = read_json(self.paths.machine_config_path(), None)
        return payload if isinstance(payload, dict) else None

    def write_global_hooks(self, hook_commands: dict[str, str], force: bool = False) -> str | None:
        path = self.paths.codex_home_hooks_path()
        if path.exists() and not force:
            return None
        atomic_write_json(path, build_hooks_payload(hook_commands))
        return str(path)

    def write_repo_hooks(self, repo_root: Path, hook_commands: dict[str, str], force: bool = False) -> str | None:
        path = repo_root / ".codex" / "hooks.json"
        if path.exists() and not force:
            return None
        atomic_write_json(path, build_hooks_payload(hook_commands))
        return str(path)

    def install_global_skill(self, template_root: Path, force: bool = False) -> str | None:
        source = template_root / ".agents" / "skills" / "autonomous-loop" / "SKILL.md"
        dest = self.paths.global_skill_path()
        if dest.exists() and not force:
            return None
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest)
        return str(dest)

    def install_repo_skill_template(self, template_root: Path, repo_root: Path, force: bool = False) -> str | None:
        source = template_root / ".agents" / "skills" / "autonomous-loop" / "SKILL.md"
        dest = repo_root / ".agents" / "skills" / "autonomous-loop" / "SKILL.md"
        if dest.exists() and not force:
            return None
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest)
        return str(dest)
