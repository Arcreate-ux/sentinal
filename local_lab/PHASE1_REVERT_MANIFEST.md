# SENTINEL Phase 1 Local Lab Revert Manifest

Purpose: keep Phase 1 development easy to remove before production deployment.

This work is intended to be local-only. It must not write to production Mongo,
production Notion, Telegram production state, or production paths.

## New Local/Additive Files

These files can be deleted to remove the local Phase 1 prototype surface:

- `brain/study_blocks.py`
- `local_lab/simulation.py`
- `local_lab/PHASE1_REVERT_MANIFEST.md`

## Shared Files With Local-Lab Hooks

These files were touched to let the local lab exercise permanent study blocks
without changing production service credentials or production database paths:

- `brain/contracts/planning.py`
  - Added optional study-block fields to `ExecutionBlock`.
  - Added `learning_confidence_level` to `PlanningContext`.
  - Revert by removing those added optional fields if production contracts must
    return to the older narrow execution-block shape.

- `brain/planner.py`
  - Normalizes generated plans into permanent study blocks.
  - Saves local fake study blocks only when the state object exposes local
    methods such as `save_study_blocks` / `save_planner_decision`.
  - Revert by removing the `StudyBlockEngine` import and the normalization/local
    persistence block.

- `brain/planning_context_builder.py`
  - Reads learning confidence only when the state object exposes
    `get_learning_confidence_level`.
  - Revert by removing that guarded read and the context field assignment.

- `brain/planning_fallback.py`
  - Preserves homework chapter/range/block type in fallback blocks.
  - Revert by removing the added metadata arguments.

- `brain/prompts.py`
  - Adds learning confidence level rules to the daily planning prompt.
  - Revert by removing the L0-L4 lines and format variable.

- `bot/commands.py`
  - Adds `/done` block-selection flow and guarded local study-block transitions.
  - Existing `/done <brain dump>` behavior remains for compatibility.
  - Revert by removing helper functions imported from `StudyBlockEngine` and
    restoring the old `cmd_done`/`cmd_skip` logic.

- `brain/orchestrator.py`
  - Adds local state-machine handlers for selected-block reflections.
  - Uses guarded study-block transition methods only when available.
  - Revert by removing `StudyBlockEngine` usage and the
    `awaiting_done_*` handlers.

- `local_lab/fake_services.py`
  - Expands fake Mongo collections and adds local-only study-block, timeline,
    planner decision, learning confidence, recovery, faculty, and prediction
    APIs.
  - Safe for production because it is under `local_lab` and writes only to
    `local_lab/runtime`.

- `local_lab/harness.py`
  - Surfaces fake Mongo collection counts and will call the local simulation
    engine.
  - Safe for production because it is under `local_lab`.

## Revert Strategy

Before production deployment, either:

1. Delete the new additive files and revert the shared hook hunks listed above.
2. Keep only the shared contract fields that production intentionally adopts.

The local-only code is deliberately guarded with method checks where possible,
so production state clients that do not implement fake-local methods should not
execute local fake Mongo writes.
