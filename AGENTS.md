# AGENTS.md

This file is a contributor contract for this repository. It is not a runtime guide for operating the plant-management skill. Runtime usage lives in `README.md` and `skill/SKILL.md`.

## Scope And Authority

- This repository wraps the shipped skill payload under `skill/`. Treat `skill/` as the packaged skill root.
- Commands in this file are written from repo root. Runtime docs may show the installed-layout form without the leading `skill/`.
- Authoritative areas:
  - Runtime code: `skill/scripts/plant_mgmt/`
  - CLI entrypoint: `skill/scripts/plant_mgmt_cli.py`
  - Tests: `skill/scripts/tests/`
  - Schemas: `skill/schemas/`
  - Seeds: `skill/seeds/`
  - Runtime docs: `README.md`, `skill/SKILL.md`
  - Package metadata: `_meta.json`, `skill/SKILL.md` frontmatter
- The on-disk layout under `skill/` is part of the implementation contract. Moves or renames require coordinated updates to path resolution, tests, and docs.

## Non-Negotiable Rules

- Keep changes narrowly scoped. Make adjacent edits only when required for correctness, tests, docs sync, or metadata sync.
- Preserve CLI and data-contract compatibility by default. Make breaking changes only when intentionally revising the public contract.
- Extend existing command groups, schema-backed files, and test modules where possible. Avoid parallel entrypoints, ad hoc runtime files, or special-case mutation paths.
- Do not treat anything inside `PLANT_DATA_DIR` as source. Runtime data, caches, `.bak`, `.tmp`, and manual test artifacts must stay outside the tracked source tree.
- Do not edit `skill/seeds/*.json` just to make tests pass. Change seeds only when the initialization baseline or data contract intentionally changes.
- Keep tests deterministic. Do not require live API keys, network access, or real provider calls in unit tests.
- Preserve the low-tooling footprint. Prefer stdlib and existing patterns before adding dependencies or contributor tooling.
- Do not bump version metadata for normal fixes, tests, docs, or refactors. Change version fields only for explicit release or packaging work.

## Verification

- Default verification for substantive changes:
  - `python3 -m unittest discover -s skill/scripts/tests -v`
- Contributor tooling:
  - `npm run test` wraps the default unit-test command for the Husky pre-commit hook.
  - `.husky/pre-commit` runs `npx lint-staged` before `npm run test`.
- Add or update tests when behavior changes. Add regression coverage for bug fixes when practical.
- Manual CLI smoke tests are additional, not default. Run them only when command parsing, env handling, or user-visible CLI behavior may have changed.
- `PLANT_SKILL_DIR` and `PLANT_DATA_DIR` are verification-only env vars for manual CLI smoke tests. They are not ordinary contributor prerequisites and are not needed for the default unit-test workflow.
- Repo-root smoke-test example:

```bash
export PLANT_SKILL_DIR=/abs/path/to/repo/skill
export PLANT_DATA_DIR=/abs/path/to/temp-data
python3 skill/scripts/plant_mgmt_cli.py init
python3 skill/scripts/plant_mgmt_cli.py check
python3 skill/scripts/plant_mgmt_cli.py --json eval status
```

- Use absolute paths for manual smoke tests and run mutating CLI commands sequentially against a fresh temporary data directory.

## Coupled Updates

- CLI contract changes: update `README.md` and `skill/SKILL.md`.
- Schema or required-file changes: keep `skill/schemas/` and matching `skill/seeds/` in sync.
- Metadata changes: keep `_meta.json` and `skill/SKILL.md` frontmatter in sync.
- Directory layout changes under `skill/`: update path-resolution code, tests, and docs together.

## Finish Checklist

- Changed behavior: add or update tests and run the unit suite.
- Changed CLI contract: update docs, run the unit suite, and run the manual smoke test.
- Changed schemas or seeds: sync both sides and run the unit suite.
- Changed metadata or frontmatter: sync both files.
- Changed only contributor workflow: update `AGENTS.md` and avoid unrelated edits.
