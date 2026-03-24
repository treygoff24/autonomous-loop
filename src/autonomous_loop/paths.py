from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

from .models import Namespace


def hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def safe_name(value: str) -> str:
    lowered = value.strip().lower()
    replaced = re.sub(r"[^a-z0-9._-]+", "-", lowered)
    return replaced.strip("-") or hash_text(value)


class RuntimePaths:
    def __init__(self, root: Path) -> None:
        self.root = root

    @classmethod
    def from_env(cls) -> "RuntimePaths":
        codex_home = Path(os.environ.get("CODEX_HOME", "~/.codex")).expanduser()
        root = Path(os.environ.get("AUTONOMOUS_LOOP_HOME", str(codex_home / "autoloop"))).expanduser()
        return cls(root.resolve())

    def resolve_repo_root(self, cwd: str | Path) -> Path:
        current = Path(cwd).expanduser().resolve()
        for candidate in (current, *current.parents):
            if (candidate / ".codex" / "autoloop.project.json").is_file():
                return candidate
            if (candidate / ".git").exists():
                return candidate
        return current

    def namespace(self, repo_root: str | Path, session_id: str) -> Namespace:
        repo = self.resolve_repo_root(repo_root)
        return Namespace(repo_root=str(repo), repo_hash=hash_text(str(repo)), session_id=session_id)

    def codex_home(self) -> Path:
        return self.root.parent

    def machine_config_path(self) -> Path:
        return self.root / "machine.json"

    def codex_home_hooks_path(self) -> Path:
        return self.codex_home() / "hooks.json"

    def global_skill_path(self) -> Path:
        return self.codex_home() / "skills" / "autonomous-loop" / "SKILL.md"

    def repo_dir(self, repo_hash: str) -> Path:
        return self.root / "repos" / repo_hash

    def project_cache_path(self, repo_hash: str) -> Path:
        return self.repo_dir(repo_hash) / "project-cache.json"

    def pending_requests_dir(self, repo_hash: str) -> Path:
        return self.repo_dir(repo_hash) / "pending-requests"

    def archived_requests_dir(self, repo_hash: str) -> Path:
        return self.repo_dir(repo_hash) / "archived-requests"

    def pending_request_path(self, repo_hash: str, request_id: str) -> Path:
        return self.pending_requests_dir(repo_hash) / f"{safe_name(request_id)}.json"

    def sessions_dir(self, repo_hash: str) -> Path:
        return self.repo_dir(repo_hash) / "sessions"

    def archived_sessions_dir(self, repo_hash: str) -> Path:
        return self.repo_dir(repo_hash) / "archived-sessions"

    def session_dir(self, namespace: Namespace) -> Path:
        return self.sessions_dir(namespace.repo_hash) / safe_name(namespace.session_id)

    def state_path(self, namespace: Namespace) -> Path:
        return self.session_dir(namespace) / "state.json"

    def contract_path(self, namespace: Namespace) -> Path:
        return self.session_dir(namespace) / "contract.json"

    def verification_path(self, namespace: Namespace) -> Path:
        return self.session_dir(namespace) / "verification.json"

    def ledger_path(self, namespace: Namespace) -> Path:
        return self.session_dir(namespace) / "ledger.json"

    def events_log_path(self, namespace: Namespace) -> Path:
        return self.session_dir(namespace) / "events.log"

    def debug_log_path(self, namespace: Namespace) -> Path:
        return self.session_dir(namespace) / "debug.log"

    def lock_path(self, namespace: Namespace) -> Path:
        return self.session_dir(namespace) / "lock"

    def ensure_repo(self, repo_hash: str) -> None:
        self.pending_requests_dir(repo_hash).mkdir(parents=True, exist_ok=True)
        self.archived_requests_dir(repo_hash).mkdir(parents=True, exist_ok=True)
        self.sessions_dir(repo_hash).mkdir(parents=True, exist_ok=True)
        self.archived_sessions_dir(repo_hash).mkdir(parents=True, exist_ok=True)

    def ensure_session(self, namespace: Namespace) -> None:
        self.session_dir(namespace).mkdir(parents=True, exist_ok=True)
