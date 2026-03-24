# Changelog

## Unreleased

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
