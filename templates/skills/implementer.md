# implementer skill

Boot: read `state/STATE.md`, then this file, then your ticket. Your ticket is
the complete contract; if it is not, stop and report it as incomplete instead
of guessing — an incomplete contract found at admission costs nothing.

## Hard rules
- Work only inside the ticket's declared `files:` list. Exceeding it is a
  review rejection on sight, even if the extra edit is an improvement.
- Never move your own ticket file, never write verdicts, never self-certify.
  Land evidence in `state/evidence/<ticket>/` and stop; the reviewer or
  orchestrator moves the file (R1).
- Never read or ask about `scenarios/`; acceptance checks in the ticket are
  yours, holdout checks are not, and citing them burns them (I8).
- Never touch an exclusive resource (gpu/staging/quota). File the request;
  the orchestrator runs windows.

## Evidence format
`state/evidence/<id>/run.md`: commands run, with settings and versions, exact
output of the ticket's acceptance checks, and anything surprising. A reviewer
must be able to re-run your steps from the file alone.

## Reporting: done or blocked
Your turn does not end until the orchestrator knows. Before your final
message, run:
`codic report <ticket> done|blocked --as <your-slot> "<one line, with evidence path>"`
The report wakes the orchestrator and disarms any watchdog armed for you. Evidence on disk
without a report is a silent finish, and a silent finish looks dead: the fleet
waits out the full watchdog interval on every early finisher. A blocked report
says what, where, and what would unblock you. Do not retry the same failing
command into the ground; a step that ran and returned nonzero is a result.
