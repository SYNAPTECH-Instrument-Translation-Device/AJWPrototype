# Plan 012: Pin the Tap SDK to the tested commit and delete the leftover `package.json`

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report. Do not improvise. When done, update the status row for this plan
> in `plans/README.md`, unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat c6e260f..HEAD -- requirements.txt package.json`
> If it prints anything, compare with "Current state". On any mismatch, STOP.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: migration / tech-debt
- **Planned at**: commit `c6e260f`, 2026-11-06

## Why this matters

1. `requirements.txt` installs the Tap SDK from the tip of its GitHub repo, with no
   version. `tapstrap/stream.py` reaches into the SDK's private internals
   (`sdk.on_raw_data` override, `sdk._write_input_mode`, `sdk.input_mode_refresh`,
   `sdk.client`). Any upstream refactor can therefore break the strap on a fresh
   install. The venv that works today was installed from commit
   `e92d13011ff95f2182604b130aeda633c225cd20` (from
   `.venv/Lib/site-packages/tap_python_sdk-1.0.0.dist-info/direct_url.json`).
2. `package.json` was copied from the GitHub "demo-repository" template. It
   declares an npm dependency on `@primer/css` that nothing in this Python
   project uses. It suggests a Node toolchain that doesn't exist.

## Current state

`requirements.txt` (whole file):
```
opencv-python==5.0.0.93
mediapipe==1.1.1
numpy==2.5.4
flask==3.1.3
tap-python-sdk @ git+https://github.com/TapWithUs/tap-python-sdk.git
matplotlib>=3.7
```

`package.json` (whole file):
```json
{
  "name": "demo-repo",
  "version": "0.2.0",
  "description": "A sample package.json",
  "dependencies": {
    "@primer/css": "17.0.1"
  },
  "license": "MIT"
}
```

## Commands you will need

| Purpose | Command | Expected |
|---|---|---|
| No references to package.json / primer | `git grep -n "package.json\|primer" -- . ':!plans'` | no output |
| Tests | `<python> -m unittest discover -s tests -t .` | `Ran 38 tests`, `OK (skipped=1, expected failures=1)` |

`<python>` is `.venv/Scripts/python.exe`, or `C:/Users/entit/projects/AJWPrototype/.venv/Scripts/python.exe`
if the worktree has no `.venv`. Do not install anything.

## Scope

**In scope**: `requirements.txt` (line 5 only), `package.json` (delete).
**Out of scope**: every other line of `requirements.txt` (plan 016 adds MIDI deps
later), `tapstrap/`, the `.venv`.

## Git workflow

One commit: `Pin the Tap SDK to the tested commit and drop the demo package.json`. Do not push.

## Steps

### Step 1: Pin the SDK
Change line 5 to:
```
tap-python-sdk @ git+https://github.com/TapWithUs/tap-python-sdk.git@e92d13011ff95f2182604b130aeda633c225cd20
```
**Verify**: `grep -c "e92d13011ff95f2182604b130aeda633c225cd20" requirements.txt` → `1`.

### Step 2: Delete package.json
`git rm package.json`.
**Verify**: the `git grep` command above prints nothing; `test -e package.json || echo gone` → `gone`.

### Step 3: Tests
**Verify**: full suite as in the table.

## Done criteria

- [ ] requirements line 5 ends in `@e92d13011ff95f2182604b130aeda633c225cd20`
- [ ] `package.json` deleted
- [ ] Full suite passes (38 tests)
- [ ] `git diff --stat HEAD~1` shows only these two files

## STOP conditions

- Something in the repo (outside `plans/`) references `package.json` or `@primer`.

## Maintenance notes

- To upgrade the SDK, bump the SHA on purpose, then rerun `python stream_raw.py`
  with a real strap. `tapstrap/stream.py` depends on private SDK attributes.
