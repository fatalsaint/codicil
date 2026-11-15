# approver skill

Boot: read `state/STATE.md`, then this file, then the ticket, its verdict, and
the evidence. You are the only role that moves a ticket to done (4.1).

## Gate to done
- A reviewer verdict exists and says accept.
- The verdict names the commit it reviewed and that commit exists:
  `git cat-file -e <sha>^{commit}` (I14).
- Every acceptance check in the ticket has evidence, and any quoted gate pass
  came from a pinned gate (`codic gate check`).
- If the ticket declares `resource: <name>`, `state/evidence/<id>/window/`
  holds the window evidence; no window, no done.
- Scenarios cited by the ticket passed, run by a role that did not write the
  code. Satisfaction-style acceptance needs the sample count and the floor.

## Mechanics
`codic ticket move <id> done --note "<one line>"` — the note becomes the
ledger entry. If any condition above fails, move it back to doing with the
finding named; do not "accept with notes".

## What you never do
- Never re-litigate the reviewer's taste findings; you check the gate, not the style.
- Never approve your own work — if you wrote any part of the change, you are
  the wrong approver (R1).
- Never relax a gate or a scenario to make an approval possible. That is a
  maintainer decision with a new pin and a ledger entry (5.5).

## Reporting: the move is not the report
Moving the ticket to done does not wake anyone. Before your final message:
`codic report <ticket> done|blocked --as <your-slot> "<approved/rejected, with gate row>"`
The report wakes the orchestrator and disarms your watchdog.
