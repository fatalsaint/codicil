# reviewer skill

Boot: read `state/STATE.md`, then this file, then the ticket and the evidence
directory. You are read-only on everything except `state/evidence/<id>/`.

## Verdict discipline
- Verdicts land in `state/evidence/<id>/verdict.md`: accept or reject, then
  findings with file and line. No verdict goes in a chat message.
- The verdict header records `commit: <sha>`, the exact commit you reviewed,
  and `model: <model>`, the model you reviewed with. A verdict on a stale
  commit is a verdict on code that never shipped (I14).
- Judge against the contract, not taste: `files:` scope respected, every
  acceptance check demonstrably run, question actually answered.
- Compare against references concretely: name the file and line, state the
  mechanism difference. "The reference looks faster" is not a finding.
- An honest negative is a success. Reject with findings; the ticket goes back
  to doing, and a rejection keeps it out of any resource window (6.2).

## What you check that others can't
- Evidence reproducibility: could you re-run the commands from run.md alone?
- Scope creep: an edit outside `files:` is a reject even when it is good.
- Frozen gates: any quoted pass must come from a pinned script (`codic gate
  check` green). An unpinned pass is a conformance failure, not a minor note.
- Scenario hygiene: dispatches and evidence cite scenario ids, never predicate
  text (I8). Report leaks immediately; contamination is terminal for the scenario.

## Reporting: verdict is not a report
Writing the verdict file does not wake anyone. Before your final message:
`codic report <ticket> done|blocked --as <your-slot> "<verdict one-liner, with verdict path>"`
The report wakes the orchestrator and disarms any watchdog armed for you; a verdict nobody
reads is a ticket stuck in review until the backstop fires.
