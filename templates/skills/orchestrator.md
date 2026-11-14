# orchestrator skill

Boot: read `state/STATE.md` (L0) in full, then this file, then the L1 rows for
the ticket ids you were handed. Never boot from a transcript (R3).

## Duties
- Decompose goals into tickets (`codic ticket new`); the ticket body is the
  complete contract — if a worker would need chat history, the ticket is not ready.
- Admit work: ready -> doing only when the worktree exists and gates are warm.
- Own exclusive-resource windows: one marker, one tool, build everything before
  taking the marker; workers never touch the resource, they file requests.
- Publish state: `codic board` after every transition you cause.

## Dispatch discipline (6.6)
`codic dispatch <id> --delta "..." --budget "..." [--send <name>]`. A dispatch
is ticket id + delta + budget, never a re-pasted brief. Wake messages are one
line; verdicts land in evidence files, not in prompts.

## Delegation budget
Name the model class in every dispatch. An unnamed delegation takes the
default slot; if the default is your own class, you just burned your slot.

## Long jobs (6.5)
`codic run --wake <name> -- <cmd>` registers the wake before launch and detaches.
Never supervise a long job inside a session; end your turn instead of waiting.

## Watchdogs: never end a waiting turn unarmed
If you end your turn waiting on an agent, arm a watchdog before you end it:
`codic watch arm <name> --why "ticket 7"`. `codic dispatch --send` arms one
automatically (30 minutes, `[watchdog]` in codic.toml; `--no-watch` only when
you armed one yourself). A worker's `codic report` disarms its watch
automatically; `codic watch cancel <id>` is only for agents that report some
other way.
A fired watch means the agent died or went silent: `codic read <name>` to see
where it stopped, then relaunch it or re-dispatch the delta. The wake line is
a nudge; `state/watches/<id>.result` is the record.

## Supersede (6.3)
Ruling changes: append the ledger entry citing `Supersedes: [Lxxx]`, then edit
the Law line in place citing the new entry. Never let a stale ruling survive in
Law; never delete from the ledger.

## Blocked state
`blocked-by` takes ticket ids or `resource:<name>`. Every `any -> blocked`
transition gets a ledger entry naming what unblocks it.
