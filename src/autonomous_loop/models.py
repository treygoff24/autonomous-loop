from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class Namespace:
    repo_root: str
    repo_hash: str
    session_id: str

    @property
    def key(self) -> str:
        return f"{self.repo_hash}:{self.session_id}"


@dataclass(slots=True)
class PendingRequest:
    request_id: str
    action: str
    nonce: str
    created_at: str
    status: str
    payload: dict[str, Any]
    claimed_by_session: str | None = None
    claimed_at: str | None = None
    applied_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "action": self.action,
            "nonce": self.nonce,
            "created_at": self.created_at,
            "status": self.status,
            "payload": self.payload,
            "claimed_by_session": self.claimed_by_session,
            "claimed_at": self.claimed_at,
            "applied_at": self.applied_at,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PendingRequest":
        return cls(
            request_id=str(payload["request_id"]),
            action=str(payload["action"]),
            nonce=str(payload["nonce"]),
            created_at=str(payload["created_at"]),
            status=str(payload["status"]),
            payload=dict(payload.get("payload", {})),
            claimed_by_session=payload.get("claimed_by_session"),
            claimed_at=payload.get("claimed_at"),
            applied_at=payload.get("applied_at"),
        )


@dataclass(slots=True)
class RuntimeState:
    version: str
    run_id: str
    session_id: str
    repo_root: str
    repo_hash: str
    contract_id: str
    objective: str
    state: str
    active: bool
    paused: bool
    gate_profile: str
    fast_gate_profile: str
    contract_hash: str
    created_at: str
    updated_at: str
    heartbeat_at: str | None = None
    iteration: int = 0
    repeated_failure_count: int = 0
    last_failure_signature: str | None = None
    last_block_reason: str | None = None
    outstanding_task_ids: list[str] = field(default_factory=list)
    last_gate_failures: list[str] = field(default_factory=list)
    released_at: str | None = None
    failed_at: str | None = None
    paused_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "run_id": self.run_id,
            "session_id": self.session_id,
            "repo_root": self.repo_root,
            "repo_hash": self.repo_hash,
            "contract_id": self.contract_id,
            "objective": self.objective,
            "state": self.state,
            "active": self.active,
            "paused": self.paused,
            "gate_profile": self.gate_profile,
            "fast_gate_profile": self.fast_gate_profile,
            "contract_hash": self.contract_hash,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "heartbeat_at": self.heartbeat_at,
            "iteration": self.iteration,
            "repeated_failure_count": self.repeated_failure_count,
            "last_failure_signature": self.last_failure_signature,
            "last_block_reason": self.last_block_reason,
            "outstanding_task_ids": list(self.outstanding_task_ids),
            "last_gate_failures": list(self.last_gate_failures),
            "released_at": self.released_at,
            "failed_at": self.failed_at,
            "paused_at": self.paused_at,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RuntimeState":
        return cls(
            version=str(payload["version"]),
            run_id=str(payload["run_id"]),
            session_id=str(payload["session_id"]),
            repo_root=str(payload["repo_root"]),
            repo_hash=str(payload["repo_hash"]),
            contract_id=str(payload["contract_id"]),
            objective=str(payload["objective"]),
            state=str(payload["state"]),
            active=bool(payload["active"]),
            paused=bool(payload["paused"]),
            gate_profile=str(payload["gate_profile"]),
            fast_gate_profile=str(payload["fast_gate_profile"]),
            contract_hash=str(payload["contract_hash"]),
            created_at=str(payload["created_at"]),
            updated_at=str(payload["updated_at"]),
            heartbeat_at=payload.get("heartbeat_at"),
            iteration=int(payload.get("iteration", 0)),
            repeated_failure_count=int(payload.get("repeated_failure_count", 0)),
            last_failure_signature=payload.get("last_failure_signature"),
            last_block_reason=payload.get("last_block_reason"),
            outstanding_task_ids=list(payload.get("outstanding_task_ids", [])),
            last_gate_failures=list(payload.get("last_gate_failures", [])),
            released_at=payload.get("released_at"),
            failed_at=payload.get("failed_at"),
            paused_at=payload.get("paused_at"),
        )


def ensure_path(value: str | Path) -> Path:
    return value if isinstance(value, Path) else Path(value)
