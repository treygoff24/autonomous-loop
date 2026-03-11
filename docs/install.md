# Install

## 1. Clone and install

```bash
git clone https://github.com/<your-org-or-user>/autonomous-loop.git
cd autonomous-loop
python3 -m pip install .
```

## 2. Install repo templates into a target project

```bash
autonomous-loop install-repo --repo /path/to/repo
```

For Node-style repos, `install-repo` generates `.codex/autoloop.project.json` from:

- `package.json`
- `package.json.packageManager`
- lockfiles
- the supported verification scripts `typecheck`, `lint`, and `test`

That command writes:

- `.codex/autoloop.project.json`
- `.codex/hooks.json`
- `.agents/skills/autonomous-loop/SKILL.md`

Override examples:

```bash
autonomous-loop install-repo --repo /path/to/repo --package-manager npm
autonomous-loop install-repo --repo /path/to/repo --prefer-scripts lint,test
```

Current v1 scope is Node-style repos with `package.json`. For non-Node repos, install the hooks and repo-local skill, then write `.codex/autoloop.project.json` manually.

## 3. Install the global skill

Copy:

- `skills/autonomous-loop/SKILL.md`

Into:

- `$CODEX_HOME/skills/autonomous-loop/SKILL.md`

If `$CODEX_HOME` is unset, Codex normally defaults to `~/.codex`.

## 4. Register global hooks

Merge `templates/.codex/hooks.json` into the `hooks.json` file for the Codex config layer you want to use.

Important:

- current Codex hook discovery uses `hooks.json`
- not `config.toml`

## 5. Restart Codex if needed

Codex usually notices new skills automatically, but a restart is still the safest path after first install.

## 6. Expect the activation boundary

When you later run `autonomous-loop request enable ...` inside Codex:

- if the response includes `activation_mode: "direct-env"`, the loop is already bound to the current Codex thread
- otherwise the CLI created a pending request
- in that fallback path, the request does not become active until the next real `Stop` hook for that session
- in that fallback path, the assistant must include the returned `AUTOLOOP_CLAIM:<nonce>` token in the final message of that turn
- in that fallback path, checking `autonomous-loop status --cwd "$PWD"` before that turn ends can still show `pending`
