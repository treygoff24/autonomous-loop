improved Ralph loop hook for Codex CLI v0.114.0+. keep your Codex agents from exiting and stopping before the implementation plan is completed. Hardened against agent tampering to cheat/manipulate early exits.

While the GPT model family is great, it's fatal flaw is early exits. you tell Codex to implement the whole plan without stopping, it does phase 1, stops, reports progress, meaning you have to babysit it, taxing your cognitive RAM in the process.

They'll also report things as done that simply are not done.

`autonomous-loop` fixes that. point your agent here to have your agent explain it to you and install it locally for you: agent-implementation-brief.md

`autonomous-loop` gives Codex a stricter definition of done. You arm it for one repo and one session. In environments that expose a stable thread or session identifier, the request binds immediately to the live session. Otherwise, the next real `Stop` hook claims it. From that point on, the stop hook checks a frozen contract, looks at the real repo state, runs the trusted gate commands you chose in repo config, and blocks exit until those checks pass. If something looks corrupted or suspicious, it fails closed instead of trusting the model.

If you do not care about the internal mechanics, the short version is simple. Install the package. Install the repo templates. Add the hook config. Use the skill to enable the loop for a task. After that, Codex keeps working until the plan is actually finished or the controller hard-stops the run because something is wrong.

## Why this exists

Without a controller like this, an agent can cheat in soft ways that are hard to catch in the moment. It can claim success early. It can skip the hard gates. It can rewrite the story of what happened after the fact. None of that requires malicious intent. It is just the natural failure mode of a system that is rewarded for sounding complete.

This project moves the definition of success out of the model’s self-report and into a separate runtime. The model can help draft the contract, but it does not get to declare that contract satisfied. The model can run commands, but it does not get to invent the commands that judge it. That separation keeps smarter but still lazy models like GPT 5.4 from simply breaking the enforcement mechanisms instead of finishing the task at hand.

## What it actually does

When you enable the loop, the runtime freezes a contract for the current task. That contract names the objective, the required tasks, the evidence each task needs, and the gate profile that decides whether the run can end. The runtime stores its mutable state under `CODEX_HOME/autoloop`, not inside the target repo, so multiple repos and multiple Codex sessions can coexist cleanly.

From there, the `Stop` hook becomes the controller. Every time Codex tries to end a turn, the hook checks whether the current repo and session are loop-controlled. If they are, it recomputes evidence from the real filesystem, runs the trusted gate commands from repo config, updates the ledger, and either blocks the stop or allows it. If the contract hash changed unexpectedly, or the runtime state is unreadable, or the same failure repeats too many times, the controller hard-stops the run instead of pretending things are fine.

There are two activation paths now. When the Codex environment exposes a stable thread or session identifier such as `CODEX_THREAD_ID`, `request enable` binds immediately to that live session and does not need a claim-token handshake. When that identifier is unavailable, activation falls back to the nonce claim handshake: the CLI writes a pending enable request and returns a token like `AUTOLOOP_CLAIM:<nonce>`, the assistant includes that token in its next message, and the next real `Stop` hook binds the request to the live session.

## What this feels like in practice

You work normally until you are ready to hand the task to the agent in a serious way. Then you enable the loop with the /autonomous-loop skill. In direct-env mode, enforcement is live immediately. In fallback mode, enforcement starts once the next `Stop` hook claims the request for the live session. After that, the agent cannot casually “wrap up” just because it thinks the coding part feels done. The contract still has to be satisfied. The evidence still has to line up. The gates still have to pass. If they do not, the hook sends the agent back into the loop with a narrow reason.

That is the practical value here. It reduces the number of fake finishes, half-finished implementations, and “trust me, it works” exits you need to babysit.

## Quickstart

Install the package:

```bash
python3 -m pip install .
```

Install the repo templates into a target project:

```bash
autonomous-loop install-repo --repo /path/to/repo
```

`install-repo` now generates `.codex/autoloop.project.json` for Node-style repos by inspecting:

- `package.json`
- `package.json.packageManager`
- lockfiles
- the supported verification scripts `typecheck`, `lint`, and `test`

Use overrides for edge cases:

```bash
autonomous-loop install-repo --repo /path/to/repo --package-manager npm --prefer-scripts lint,test
```

Current v1 scope is Node-style repos with `package.json`. For non-Node repos, install the hooks and skill, then write `.codex/autoloop.project.json` manually.

Then do two small setup steps:

1. Copy [`skills/autonomous-loop/SKILL.md`](skills/autonomous-loop/SKILL.md) into your Codex skills directory.
2. Merge [`templates/.codex/hooks.json`](templates/.codex/hooks.json) into the `hooks.json` file for the Codex config layer you actually use.

Once that is in place, use the `autonomous-loop` skill inside Codex to enable the loop for the current task.

Important for testing inside Codex CLI:

- if `request enable` returns `activation_mode: "direct-env"`, the loop is already bound to the current session
- otherwise the request is pending until the next real `Stop` hook claims it
- in the fallback path, `autonomous-loop status --cwd "$PWD"` can still show `pending` during the same active turn that printed the claim token
- in the fallback path, the expected activation point is the end of the next assistant turn whose final message includes the exact token

## Repo and session isolation

This system is scoped by `repo_hash + session_id`. That means one noisy run in one repo does not spill into another repo, and two Codex sessions in the same repo can still be tracked separately. Each run gets its own state, contract, verification bundle, ledger, events log, and lock file.

## What engineers should read next

If you want the operational details, start here:

- [`docs/install.md`](docs/install.md)
- [`docs/examples.md`](docs/examples.md)
- [`docs/security.md`](docs/security.md)
- [`docs/agent-implementation-brief.md`](docs/agent-implementation-brief.md)
- [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md)

If you want the short version for a coding agent, hand it [`agent-implementation-brief.md`](docs/agent-implementation-brief.md). That file is written as a direct system brief, not marketing copy.

## Current hook assumptions

This project is built around the verified Codex CLI `0.114.0` hook model:

- `SessionStart` and `Stop` exist
- hooks are discovered from `hooks.json`
- `Stop` groups are discovered without a matcher
- only `command` hooks are currently usable for this controller

The main upstream quirk is that live hook registration belongs in `hooks.json`, not `config.toml`.
