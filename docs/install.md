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

That installs:

- `.codex/autoloop.project.json`
- `.codex/hooks.json`
- `.agents/skills/autonomous-loop/SKILL.md`

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
