# Teaching notes

- 2026-11-07: First /teach request: "explain what changes you have made and how you implemented them". Mission was inferred from that and the session; confirm with the user.
- The user is the repo owner, has written Python here, and knows the hardware. Start from code they can open, not from theory.
- Lesson 1 covers the tap → note path. Candidate next lessons: the strap thread (asyncio inside a thread, the lock, stop/typing mode); calibration reload (`checked_size`); testing with fakes (FakePort, SimpleNamespace); the plan → executor → review workflow.
- No GLOSSARY.md yet. Add terms (event, refractory, deviation, strap hand) once the user uses them correctly.
- Workspace files sit in the repo root, untracked. Ask whether to commit them, move them, or add them to .git/info/exclude.
