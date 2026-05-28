## Summary

<!-- What does this PR do? One or two sentences. -->

## Changes

<!-- What files changed and what was done to them. -->

## Roadmap

- [ ] If this PR implements a ROADMAP.md item, ROADMAP.md is updated in this PR
- [ ] Completed roadmap work is moved into the Completed section

## Database migrations

- [ ] This PR does not change the SQLite schema
- [ ] If it changes the SQLite schema, the PR includes the migration module,
      existing-row population/default/nullability plan, lazy-migration safety
      notes, any required background backfill or re-embedding plan, and upgrade
      tests from the previous schema version

## Quality gates

- [ ] `uv run ruff check .` passes
- [ ] `uv run pyright` passes
- [ ] `uv run pytest` passes
- [ ] `uv run pytest --cov=src/recollectium --cov-report=term-missing` targets 100% on changed code

## Policy compliance

- Pytest success rate:
- Test coverage for this feature:
- Test coverage for codebase:
- Ruff status:
- Pyright status:
