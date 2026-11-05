# Pinned CPU frontend test fixture

`FreeJ2ME.java.txt` is the unmodified FreeJ2ME-Plus frontend source with line
endings normalized to LF. Its original GPL-3.0-or-later notice is retained.
The project's root `LICENSE` includes the GPL text. This is emulator source;
it contains no game or user data.

- Upstream: https://github.com/TASEmulators/freej2me-plus
- Revision: `3933e75ef927a95eab9f5e065f0b76dabf336069` (the revision pinned in `tools/build.py`)
- Source path: `src/org/recompile/freej2me/FreeJ2ME.java`
- SHA-256 of UTF-8 text after LF normalization:
  `3807282d28dcf45fefe94685a42ce7bce852856528b056c4dd3ef2d1cefa1d2f`

The patcher contract test reads this fixture so a clean checkout can run the
Python suite without downloading or building the emulator, Git subprocesses,
or network access. It still applies the production patch and checks that a
second application produces the same source.

When updating the pinned emulator revision, obtain this file with
`git show <revision>:src/org/recompile/freej2me/FreeJ2ME.java` in the upstream
checkout, normalize line endings, and update this provenance and the test hash.
Review the production patch anchors against the new source before accepting
the updated fixture.
