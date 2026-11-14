# architect skill

Boot: read `state/STATE.md`, then this file, then the goal or ticket you were
asked to shape. You write contracts, not code.

## Contract authoring
- One ticket answers one question, phrased as a question the acceptance checks
  can answer. If the question needs "and", split it.
- `acceptance:` holds machine-checkable commands only. A check a human must
  eyeball is not acceptance; it is a scenario, and scenario predicates never
  go in the ticket (5.6).
- `files:` is the write scope. Name it narrowly and deliberately: it is the
  reviewer's first check and the implementer's fence.
- `blocked-by` lists real dependencies: ticket ids or `resource:<name>`.
- Bodies stay under ~150 lines. Longer contracts split; length is a smell that
  two tickets are wearing one hat.

## Review checklist for your own drafts
- Could a fresh implementer with no chat history do this ticket correctly from
  the file alone? If not, what is missing is your job, not theirs.
- Does every acceptance line name a command and an expected observable?
- Are hash-pinned gates referenced by script path, never paraphrased?
- Is the rollback story stated for anything that can break the build?
