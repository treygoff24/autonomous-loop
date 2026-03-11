# Contributing

## Development setup

```bash
python3 -m pip install -e .
python3 -m unittest discover -s tests -v
python3 -m compileall src bin
```

## Change guidelines

- Keep trusted gate execution on argv arrays with `shell=False`.
- Keep mutable runtime state under `CODEX_HOME/autoloop`.
- Preserve fail-closed behavior on corrupted runtime state.
- Update docs and templates when changing runtime behavior.

## Pull requests

- include tests for behavior changes
- keep diffs focused
- call out any upstream Codex hook behavior changes explicitly
