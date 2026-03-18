# Sophia Forge Eval Corpus

This directory holds replayable coding-task fixtures for Phase 2 runtime evaluation.

Each case is a JSON document with:

- `case_id`
- `name`
- `description`
- `tags`
- `request`
- `expectation`

The request payload is a full `RunRequest` fixture. The expectation currently captures:

- expected terminal `status`
- whether required verification should pass
- optional changed-file subset checks
- optional normalized `failure_class`

These fixtures are intended to come from real coding tasks over time, then be replayed
through the forge executor to compare backend behavior and prompt changes.
