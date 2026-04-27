# Changelog

## Unreleased

## 0.2.0 - 2026-04-27

- Added plan-aware Stop-hook enforcement: `autonomous-loop` now reads the latest Codex transcript `update_plan` state and blocks exit while any plan item is not `completed`.
- Increased the Stop hook timeout from 60 seconds to 600 seconds so longer verification gates can finish before Codex exits.
- Made repo-local `.codex/hooks.json` opt-in with `install-repo --install-hooks`; global `$CODEX_HOME/hooks.json` is now the default enforcement path across profiles.
- Updated `doctor --cwd` to accept matching repo-local autonomous-loop hooks with a warning and fail only stale or mismatched repo hooks.
- Expanded `install-repo` autodetection beyond basic Node scripts: Node combined scripts (`check`, `quality`, `ci`), standard Node scripts (`typecheck`, `lint`, `test`), Make, Python, Rust, and Go are now supported.
- Added profile-switcher preflight support for local Codex profile workflows so version drift can be refreshed automatically on profile switches.
- Rewrote the autonomous-loop skill with explicit trigger phrases, mandatory `update_plan` discipline, fresh-context recovery, and a mechanical activation/work loop.
- Added `agents/openai.yaml` metadata to improve future Codex/human skill discovery.
- Added `autonomous-loop agent-instructions --cwd <path>` to print fresh-context instructions, trusted gate refs, an enable-command template, and an AGENTS.md snippet.
- Added regression tests for transcript plan parsing, plan-gated Stop behavior, skill discovery text, packaged skill metadata, repo-hook opt-in behavior, and broader install autodetection.
- Updated setup, troubleshooting, examples, and agent-facing docs for the global-hook/default profile-sharing model.

## 0.1.1 - 2026-03-24

- Added machine bootstrap with `autonomous-loop bootstrap`, which writes the global hooks file, global skill, and machine config under `CODEX_HOME`
- Added `autonomous-loop doctor` for machine-level and repo-level validation, with non-zero exit on failed checks
- `install-repo` now requires successful machine bootstrap and renders repo-local hooks from the verified machine command path
- Reworked onboarding docs around the two-step flow: bootstrap once, then install each repo
- `install-repo` still autodetects Node-style repos with `package.json`
- `install-repo` detects package manager with precedence `--package-manager` -> `package.json.packageManager` -> lockfiles
- `install-repo` trusts only the supported verification scripts `typecheck`, `lint`, and `test`, generates explicit trusted command argv arrays, and fails closed on unsafe installs
- Added direct session binding for `request enable` when `CODEX_SESSION_ID` or `CODEX_THREAD_ID` is available, with fallback claim-token activation when no live session identifier is exposed
- Added direct-env handling for follow-up actions when the target session already has loop state
- Added archive-first runtime cleanup with `autonomous-loop cleanup`, automatic repo cleanup on `SessionStart`, and archived session/request bookkeeping under the runtime root
- Added session heartbeat tracking, freshness-based active-session selection, and direct-enable stale sibling cleanup to reduce multi-session drift
- Added non-failing `runtime_hygiene` doctor reporting plus richer `status` output with hygiene summaries and archived artifact counts
- Added an agent-first installation and troubleshooting guide in `AGENT_BUILD_GUIDE.md`

## 0.1.0

- Initial public packaging of the Codex autonomous-loop runtime
- Standalone CLI, hooks, templates, skills, docs, and tests
