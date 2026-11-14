# maintainer skill (human)

You own goals, gates, law, and scenarios. Two minutes a day:

1. Read `state/STATE.md`. Census gives queue counts, gate rows, the critical
   path, resource holders, and the roster. That is the whole status meeting.
2. Drill down only when a row interests you: the BOARD line, then the ticket.
3. Decide by editing your Law lines (`codic law add` or edit in place) and
   appending a ledger entry. That is the only mechanism for changing policy.
4. Direct with one line: `codic prompt orchestrator "<what and why>"`.
5. Verify with `codic check; echo $?`.

## Rules of thumb
- Never paste context into an agent session. If an agent needs to know
  something, it belongs in Law, a skill, a ticket, or the ledger.
- Never quote a rate or pass from an unpinned gate run.
- When a fresh session acts wrongly, fix the file it read, not the session.
- Your scarce resource is decisions, not information. Approve nothing routine;
  the approver role moves tickets to done. You move Law, gates, goals, scenarios.
