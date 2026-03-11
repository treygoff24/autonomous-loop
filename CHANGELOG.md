# Changelog

## Unreleased

- Added `install-repo` autodetect for Node-style repos with `package.json`
- `install-repo` now detects package manager with precedence `--package-manager` -> `package.json.packageManager` -> lockfiles
- `install-repo` now trusts only the supported verification scripts `typecheck`, `lint`, and `test`, generates explicit trusted command argv arrays, and fails closed on unsafe installs
- Added direct session binding for `request enable` when `CODEX_SESSION_ID` or `CODEX_THREAD_ID` is available, with fallback claim-token activation when no live session identifier is exposed
- Added direct-env handling for follow-up actions when the target session already has loop state

## 0.1.0

- Initial public packaging of the Codex autonomous-loop runtime
- Standalone CLI, hooks, templates, skills, docs, and tests
