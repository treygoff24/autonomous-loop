from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class PlanItem:
    step: str
    status: str


@dataclass(frozen=True, slots=True)
class PlanSnapshot:
    items: tuple[PlanItem, ...]

    @property
    def incomplete_items(self) -> tuple[PlanItem, ...]:
        return tuple(item for item in self.items if item.status != "completed")

    @property
    def is_complete(self) -> bool:
        return not self.incomplete_items


def load_latest_plan_snapshot(transcript_path: str | None) -> PlanSnapshot | None:
    if not transcript_path:
        return None
    path = Path(transcript_path).expanduser()
    if not path.is_file():
        return None

    latest: PlanSnapshot | None = None
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            snapshot = _plan_snapshot_from_line(line)
            if snapshot is not None:
                latest = snapshot
    return latest


def describe_incomplete_plan(snapshot: PlanSnapshot) -> str:
    grouped: dict[str, list[str]] = {}
    for item in snapshot.incomplete_items:
        grouped.setdefault(item.status, []).append(item.step)
    parts = []
    for status in sorted(grouped):
        steps = "; ".join(grouped[status])
        parts.append(f"{status}: {steps}")
    return "Plan incomplete: " + " | ".join(parts)


def _plan_snapshot_from_line(line: str) -> PlanSnapshot | None:
    try:
        record = json.loads(line)
    except json.JSONDecodeError:
        return None
    payload = record.get("payload") if isinstance(record, dict) else None
    if not isinstance(payload, dict):
        return None
    if payload.get("type") != "function_call" or payload.get("name") != "update_plan":
        return None
    arguments = _parse_arguments(payload.get("arguments"))
    if not isinstance(arguments, dict):
        return None
    return _plan_snapshot_from_payload(arguments)


def _parse_arguments(arguments: Any) -> Any:
    if isinstance(arguments, str):
        try:
            return json.loads(arguments)
        except json.JSONDecodeError:
            return None
    return arguments


def _plan_snapshot_from_payload(payload: dict[str, Any]) -> PlanSnapshot | None:
    raw_items = payload.get("plan")
    if not isinstance(raw_items, list):
        return None
    items: list[PlanItem] = []
    for raw_item in raw_items:
        item = _plan_item_from_payload(raw_item)
        if item is not None:
            items.append(item)
    if not items:
        return None
    return PlanSnapshot(tuple(items))


def _plan_item_from_payload(payload: Any) -> PlanItem | None:
    if not isinstance(payload, dict):
        return None
    step = payload.get("step")
    status = payload.get("status")
    if not isinstance(step, str) or not step.strip():
        return None
    if not isinstance(status, str) or not status.strip():
        status = "unknown"
    return PlanItem(step=step.strip(), status=status.strip())
