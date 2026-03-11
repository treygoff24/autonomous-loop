from __future__ import annotations

import dataclasses
import importlib
import inspect
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
BIN_ROOT = PROJECT_ROOT / "bin"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


MODULE_CANDIDATES = (
    "autonomous_loop.api",
    "autonomous_loop.runtime",
    "autonomous_loop.loop",
    "autonomous_loop.manager",
    "autonomous_loop",
)

CLASS_CANDIDATES = (
    "AutonomousLoopRuntime",
    "LoopRuntime",
    "Runtime",
    "AutonomousLoopManager",
)

CAPABILITY_NAMES = {
    "enable": ("enable", "start", "activate", "enable_loop", "start_run", "activate_loop"),
    "stop": ("stop", "evaluate_stop", "stop_hook", "run_stop_gate", "check_stop", "gate_stop"),
    "pause": ("pause", "pause_run"),
    "resume": ("resume", "resume_run"),
    "install_repo": ("install_repo", "install", "install_into_repo"),
    "wrap_hook": (
        "wrap_hook_result",
        "hook_wrapper",
        "normalize_hook_output",
        "normalize_hook_result",
        "sanitize_hook_result",
    ),
}


class ContractError(AssertionError):
    """Raised when the runtime does not satisfy the expected public contract."""


class RuntimeAdapter:
    def __init__(self) -> None:
        self.modules = self._load_modules()
        self.host = self._build_host()

    def _load_modules(self) -> list[Any]:
        loaded = []
        seen = set()
        for name in MODULE_CANDIDATES:
            try:
                module = importlib.import_module(name)
            except ModuleNotFoundError:
                continue
            except Exception as exc:
                raise ContractError(f"Import failed for {name}: {exc}") from exc
            if module.__name__ not in seen:
                loaded.append(module)
                seen.add(module.__name__)
        if not loaded:
            raise ContractError(
                f"Could not import an autonomous-loop runtime from {SRC_ROOT}. "
                f"Tried: {', '.join(MODULE_CANDIDATES)}"
            )
        return loaded

    def _build_host(self) -> Any | None:
        for module in self.modules:
            for class_name in CLASS_CANDIDATES:
                runtime_cls = getattr(module, class_name, None)
                if not inspect.isclass(runtime_cls):
                    continue
                try:
                    return runtime_cls()
                except TypeError:
                    continue
        return None

    def resolve(self, capability: str) -> Any:
        names = CAPABILITY_NAMES[capability]
        search_roots = [self.host] if self.host is not None else []
        search_roots.extend(self.modules)
        for root in search_roots:
            if root is None:
                continue
            for name in names:
                candidate = getattr(root, name, None)
                if callable(candidate):
                    return candidate
        tried = ", ".join(names)
        roots = ", ".join(module.__name__ for module in self.modules)
        raise ContractError(f"Could not resolve capability '{capability}' in [{roots}]. Tried: {tried}")

    def call(self, capability: str, **kwargs: Any) -> Any:
        function = self.resolve(capability)
        return invoke_flexible(function, **kwargs)

    def has_capability(self, capability: str) -> bool:
        try:
            self.resolve(capability)
        except ContractError:
            return False
        return True


def invoke_flexible(function: Any, **kwargs: Any) -> Any:
    signature = inspect.signature(function)
    parameters = signature.parameters

    if any(parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in parameters.values()):
        return function(**kwargs)

    filtered = {name: value for name, value in kwargs.items() if name in parameters}
    if filtered:
        return function(**filtered)

    if len(parameters) == 1:
        name, parameter = next(iter(parameters.items()))
        if parameter.kind in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        ):
            if name in {"context", "request", "payload", "state", "options", "params"}:
                return function(kwargs)

    return function()


def to_mapping(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if dataclasses.is_dataclass(value):
        return dataclasses.asdict(value)
    if hasattr(value, "_asdict"):
        return dict(value._asdict())
    if hasattr(value, "__dict__"):
        return {
            key: item
            for key, item in vars(value).items()
            if not key.startswith("_") and not callable(item)
        }
    return {}


def normalize_action(result: Any) -> str:
    data = to_mapping(result)
    text_candidates = []

    for key in ("action", "decision", "status", "result"):
        value = data.get(key)
        if isinstance(value, str):
            text_candidates.append(value)

    for key in ("message", "reason", "detail"):
        value = data.get(key)
        if isinstance(value, str):
            text_candidates.append(value)

    if isinstance(result, str):
        text_candidates.append(result)

    lowered = " ".join(text_candidates).lower()
    if any(token in lowered for token in ("hard_stop", "hard-stop", "hard stop", "manual intervention")):
        return "hard_stop"
    if any(token in lowered for token in ("noop", "no-op", "disabled", "skip")):
        return "noop"
    if any(token in lowered for token in ("allow", "release", "green", "complete", "pass")):
        return "allow"
    if any(token in lowered for token in ("block", "blocked", "fail", "continue")):
        return "block"

    if data.get("hard_stop") is True or data.get("paused") is True and data.get("manual_intervention") is True:
        return "hard_stop"
    if any(data.get(key) is True for key in ("allow_exit", "release", "released", "allowed")):
        return "allow"
    if any(data.get(key) is True for key in ("noop", "disabled", "skipped")):
        return "noop"
    if any(data.get(key) is True for key in ("block_exit", "blocked")):
        return "block"

    if isinstance(result, bool):
        return "allow" if result else "block"

    return "unknown"


def json_files_under(project_dir: Path) -> list[Path]:
    return sorted(path for path in project_dir.rglob("*.json") if path.is_file())


def load_json(path: Path) -> dict[str, Any] | None:
    try:
        parsed = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def discover_artifacts(project_dir: Path) -> dict[str, dict[str, Any]]:
    state_candidates: list[dict[str, Any]] = []
    contract_candidates: list[dict[str, Any]] = []

    for path in json_files_under(project_dir):
        data = load_json(path)
        if not data:
            continue

        keys = {key.lower() for key in data}
        path_name = path.name.lower()

        is_state = (
            bool({"goal", "iteration", "paused", "active", "run_id", "session_token"} & keys)
            or "state" in path_name
        )
        is_contract = (
            "contract_hash" in keys
            or "contract" in path_name
            or ("hash" in keys and "run_id" in keys)
        )

        candidate = {"path": path, "data": data}
        if is_state:
            state_candidates.append(candidate)
        if is_contract:
            contract_candidates.append(candidate)

    state = next((item for item in state_candidates if "state" in item["path"].name.lower()), None)
    if state is None and state_candidates:
        state = state_candidates[0]

    contract = next((item for item in contract_candidates if "contract" in item["path"].name.lower()), None)
    if contract is None and contract_candidates:
        contract = contract_candidates[0]

    if state is None:
        raise ContractError(f"Could not locate a state artifact under {project_dir}")
    if contract is None:
        raise ContractError(f"Could not locate a contract artifact under {project_dir}")
    if state["path"] == contract["path"]:
        raise ContractError("State and contract artifacts must be persisted separately")

    return {"state": state, "contract": contract}


def artifact_run_id(artifact: dict[str, Any]) -> str | None:
    data = artifact["data"]
    for key in ("run_id", "session_token", "token", "id"):
        value = data.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def artifact_contract_hash(artifact: dict[str, Any]) -> str | None:
    data = artifact["data"]
    for key in ("contract_hash", "hash", "sha256"):
        value = data.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def state_is_active(project_dir: Path) -> bool:
    try:
        artifacts = discover_artifacts(project_dir)
    except ContractError:
        return False
    data = artifacts["state"]["data"]
    if data.get("paused") is True:
        return False
    if data.get("active") is False:
        return False
    if data.get("enabled") is False:
        return False
    return True


def meaningful_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode()
    return str(value)


def make_temp_repo(prefix: str = "autonomous-loop-test-") -> Path:
    return Path(tempfile.mkdtemp(prefix=prefix))


def make_node_repo(
    root: Path,
    *,
    package_manager: str | None = None,
    scripts: dict[str, str] | None = None,
    lockfiles: tuple[str, ...] = (),
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    package_json: dict[str, Any] = {
        "name": "fixture-repo",
        "private": True,
        "version": "0.0.0",
        "scripts": scripts or {},
    }
    if package_manager is not None:
        package_json["packageManager"] = package_manager

    (root / "package.json").write_text(json.dumps(package_json, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    for lockfile in lockfiles:
        (root / lockfile).write_text("# fixture\n", encoding="utf-8")
    return root


def load_installed_project_config(repo_root: Path) -> dict[str, Any] | None:
    return load_json(repo_root / ".codex" / "autoloop.project.json")


def run_install_repo_cli(
    repo_root: Path,
    *,
    force: bool = False,
    package_manager: str | None = None,
    prefer_scripts: list[str] | None = None,
) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, str(BIN_ROOT / "autoloop_cli.py"), "install-repo", "--repo", str(repo_root)]
    if force:
        command.append("--force")
    if package_manager is not None:
        command.extend(["--package-manager", package_manager])
    if prefer_scripts:
        command.extend(["--prefer-scripts", ",".join(prefer_scripts)])
    return subprocess.run(command, cwd=PROJECT_ROOT, capture_output=True, text=True, check=False)
