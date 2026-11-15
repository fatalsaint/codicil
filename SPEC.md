# Fleet Spec: a state architecture for agent-built software

Status: draft 3, 2026-11-14. Draft 1 was reviewed by a live fleet's orchestrator;
six findings, five accepted as filed, one accepted with a partial disagreement
(exclusive per-line Law ownership instead of blanket maintainer ownership, 5.1).
Draft 3 generalized the spec for open-source release: the reference deployment,
a local-inference fleet on consumer AMD silicon, is cited throughout as "the
reference fleet", and its instantiation annex was removed.
Sources: StrongDM Software Factory (factory.strongdm.ai, Principles and Techniques pages),
Simon Willison's writeup of 2026-02-07, strongdm/attractor specs, and two years of
postmortems from a production agent harness.

---

## 1. Purpose

This spec defines the state layer for a fleet of coding agents that build software
with bounded human review. It is deliberately not an agent loop, not a task runner,
and not a prompt library. It answers exactly three questions:

1. What must an agent read when it starts, so that a fresh session can act correctly
   without inheriting a transcript?
2. Where does current truth live, so that a superseded ruling can never be mistaken
   for an active one?
3. What decides whether work is accepted, so that the party producing a result is
   never the sole party judging it?

The design goal, in one line: **a fleet agent's boot reading is small, bounded,
and the whole of its orientation: L0 plus its role's skill set; everything else
is expanded on demand by id.**

This spec is repo-agnostic. Section 9 says what transfers unchanged, what each repo
must supply, and how to check conformance.

## 2. Non-goals

- Not an agent framework. Any harness that runs named, promptable sessions qualifies
  (Herdr, tmux, tmux-like multiplexers, container-per-agent, plain process supervision).
- Not a scheduler. Ticket ordering is the orchestrator's judgement, constrained here
  only by dependency and resource rules.
- Not a replacement for gates, CI, or numerical validation. It defines who runs them,
  what they may read, and how their results become state.
- Not about model selection. The role-to-model mapping is a per-repo binding (9.2).

## 3. The failure this fixes

Observed on a real fleet, measured 2026-11-12:

| artifact | size | approx tokens |
| --- | --- | --- |
| handoff brief | 1,169 lines / 64 KB | 16k |
| append-only notes ledger | 429 lines / 174 KB, 292 entries | 43.5k |
| generated board | 312 lines | 5.5k |
| all tickets | 12,944 lines | ~238k |
| evidence tree | 29 GB | not readable at all |
| dispatch prompts and agent transcripts | one implementer session compacted at 207K tokens (orchestrator report, 2026-11-12); the dispatches feeding it were re-pasted briefs | exceeds the working window |

The orchestrator's mandatory boot reading was ~60k tokens before touching a ticket.
Superseded rulings, corrections, and corrections-of-corrections sat in one
append-only log at equal weight; 19 entries contained the word "supersedes", so
supersession happened by accretion, not by edit. The runbook itself carried 23
references to a harness generation that had been deleted. The agent was not losing
its mind. It was being handed a pile with no zoom levels and no way to tell law
from history, and then asked to reason.

Every mechanism in sections 4 through 8 exists to make one or more rows of that
table impossible.

## 4. Core model

### 4.1 Roles

A fleet has exactly these role classes. Names are stable across sessions.

| role | duty | may write |
| --- | --- | --- |
| maintainer | human. Owns goals, gates, and this spec's per-repo bindings | everything |
| orchestrator | Decomposes goals into tickets, admits work, owns exclusive-resource windows, publishes state | tickets, its own operational law lines (5.1), ledger |
| architect | Turns a product need into a ticket contract. Writes no code | tickets |
| implementer | Makes an authorized ticket's tests pass, inside the ticket's declared file list | its worktree |
| reviewer | Independent read-only judgment of a change against contract, tests, risk | evidence only |
| approver | Final accept/block. The only role that moves a ticket to done | ticket state |
| supervisor | Dumb daemon that runs long device/build jobs detached from any agent session and wakes named agents on completion | its own log files |

Hard rules:

- R1. No agent writes its own acceptance. The implementer emits evidence; the
  reviewer reads it; the approver moves state. One role, one hat, per ticket.
- R2. Every pane, session, or process that represents a role has a stable name
  (`orchestrator`, `impl1`, `arch1`, `rev1`, ...). Addressing an agent by pane id,
  tty, or pid is prohibited in every script and every dispatch prompt, because
  layout changes silently break wake paths.
- R3. The orchestrator is stateless across sessions by construction. Its boot
  procedure (6.1) is the only legitimate way to become oriented. "Continue from
  where we left off" with a transcript attached is an anti-pattern this spec
  forbids for routine operation.
- R4. Operational knowledge belongs to roles, not to sessions. Each role has a
  declared skill set (4.4) that is part of its boot reading. A lesson that must
  be re-derived every session because it lives in no skill file is a defect in
  the skill layer, not a cost of statelessness.

### 4.2 The state pyramid

Three zoom levels for state. An agent boots at L0 plus its role skill set (4.4)
and expands downward by id, never sideways.

**L0, the law file (`STATE.md`).** The orchestrator's orientation file, read
together with its role skill set (4.4). It has two sections with different
editors and different budgets:

- `## Law`: curated, edited in place. Current rulings only, each citing the
  ledger entry that created it (`[L187]`). When a ruling changes, the line is
  edited here and the superseded text is appended to the ledger (6.3). A law
  line is a self-contained imperative addressed to a role, **including the
  clause that names its own misreading**. Compressed law that can be followed
  in the letter and violated in the purpose is worse than no law: the agent
  satisfies the check and burns the resource anyway. The delegation rule is
  the test case. "Implementer subagents cost nothing local; a plain task
  subagent takes a slot" is only load-bearing with the trap stated: `task` is
  the default role and it is local, so an unnamed delegation burns the slot.
  A ruling that cannot carry its counterexample in a few lines is not law; it
  is a skill (4.4) or a gate. Each line carries exactly one owner class, and
  only that class edits it (5.1).
- `## Census`: generated. Queue counts per state, gate rows with live numbers
  and pass/fail, the critical path as ticket ids with one line each, resource
  state including named holders (window open/closed, engine up/down, resource
  held by a maintainer experiment), and the fleet roster with pane names and
  wake registrations. Summary-shaped: counts and critical path, never
  per-ticket rows, which belong to L1. Regenerated by the board tool (5.7).
  Tools never rewrite `## Law`; humans and the orchestrator never hand-edit
  `## Census`.

**L1, the board (`BOARD.md`).** Generated. One row per ticket: id, role, worktree,
one-line question, state, age. Budget: 8,192 tokens. The board tool must parse
every ticket that exists, including legacy prose tickets, and must fail loudly on
a ticket it cannot parse rather than rendering `?`.

**L2, full detail.** Tickets, evidence directories, logs, transcripts. Expanded by
id, on demand, by whoever needs it. No budget, because nothing boots on it.

Budgets are enforced per section by the generator, which exits nonzero on any
violation and the fleet stops until it is compressed: Law 2,048 tokens, Census
1,024, L1 8,192. Census gets its own budget rather than an exemption, because
being generated it cannot accrete prose but it can still grow rows. A budget
nobody checks is a suggestion.

### 4.3 Law and ledger, separated

Two files, opposite write rules:

- **The ledger (`NOTES.md`)** is append-only forever. Every ruling, measurement,
  correction, incident, and reversal lands here with a UTC timestamp and a
  monotonic entry id. Entries are never edited. A superseding entry names the id
  it supersedes. This is the audit trail; it is also the source that L0 Law cites.
- **The law file (`STATE.md` `## Law`)** is rewritten in place. It contains only
  rulings that are true right now. Its correctness criterion: a fresh
  orchestrator that reads L0 and its role skill set, and acts on them alone,
  acts correctly.

The failure mode this splits: an append-only log makes "the arena change broke
block parity" and "block parity is fixed, ticket 61 closed" sit 200 KB apart at
equal weight. Under this spec the second event edits the law line and appends the
first to the ledger's superseded history. The fresh agent never reads the dead
ruling unless it expands the citation.

### 4.4 The skill layer

L0 alone is not the whole boot reading, and a spec that pretends otherwise just
moves the failure into re-deriving lessons every session. What makes a working
loop work is mostly not law-shaped knowledge. It is position/payload-length
arithmetic, chunk-boundary confound structures, cross-path pairing rules:
operational knowledge that belongs to a role, not to a ruling and not to a
session. It lives in skills, one declared set per role, loaded at boot after L0
and before any ticket (6.1).

The line between law and skill:

- Law is a ruling. It changes when policy changes, it has an owner, it cites
  the ledger. "Admission to the device is marker presence, never a free-memory
  floor."
- A skill is operational knowledge. It stays true across rulings, it is bound
  to a role, it cites measurements and worked examples. "At 2,048 rows per
  expert the MoE tile is launch-bound; here is the arithmetic and here is the
  window that proved it."

A law line that reads like procedure is misplaced: move it to the role's skill
set. Skills are a per-repo binding (9.2), not a fourth zoom level. The pyramid
zooms on state; skills attach to roles. Each role's skill set is one declared
file with a budget that `codic check` enforces (I12). A skill that no boot loads
is dead prose; a lesson that every session re-derives is a missing skill, and
writing it down is itself a ticket.

## 5. Artifacts and formats

### 5.1 `STATE.md` (L0)

```markdown
# STATE — <repo> fleet
Generated census at <UTC stamp>. Law section is curated; edit in place,
cite the ledger entry, append the superseded text to NOTES.md.

## Law
- [L187] Gates are law. bench-gate.sh is hash-pinned; never relax it, and
  never quote a pass that did not come from it, including any rate from a
  profiled run, which is the misreading that flatters. (maintainer, 2026-11-08)
- [L203] Admission to the device is engine presence and window state, never a
  free-memory floor: a floor once admitted a build with 350 MiB spare against
  an engine pinned at 89 GB and hard-killed the box, so "memory looked fine"
  is never grounds to override the check. (orchestrator, 2026-11-06)
...

## Census
generated below by <board-tool>; do not edit
```

Format rules for Law lines: imperative, addressed to a role, carrying a ledger
citation and an owner tag. Ownership is exclusive per line, and the classes are
by subject: maintainer owns goals, gates, role authority, and anything touching
this spec; the orchestrator owns operational law (admission, window policy,
dispatch). A line's owner never changes without a maintainer decision, and the
orchestrator proposes maintainer-class changes as ledger entries, never as
edits. Blanket maintainer ownership of all Law was considered and rejected: it
either stalls daytime operations or turns the human into a rubber stamp, and a
stale Law file is the disease this spec treats. A law line without a citation,
an owner, or its counterexample clause is a conformance failure. More than ~25
law lines, or any line that needs more than four prose lines to carry its
counterexample, signals something being memorized instead of decided: compress
it, move it to a skill, or promote it to a gate.

### 5.2 `BOARD.md` (L1)

Generated table, one row per ticket, grouped by state directory. Columns:
`ticket | role | worktree | question | age`. State is the directory a ticket file
lives in; the board is derived from directories and never edited by hand.

### 5.3 Tickets (L2)

One file per ticket, in a state directory (`ready/ doing/ review/ reviewed/ gpu/
blocked/ done/`). Moving the file is the only state transition. Frontmatter is
required and machine-parsed:

```yaml
id: 61
title: restore block-parity per-token path
role: implementer            # who may work it
worktree: work/wt/61-parity
engine: cloud                # local | cloud, for budget accounting
model: claude-opus-4-1       # stamped by dispatch --send from the roster; feeds I15
files:                       # write scope; exceeding it is a review rejection
  - src/gpu/block.rs
question: >                  # one line, appears verbatim on the board
  Does the per-token parity path match FP32 reference logits after the FP16 arena change?
acceptance:                  # machine-checkable checks, see 5.6 for what must NOT go here
  - scripts/gate 61 exits 0
  - examples/block-parity prints PARITY_OK
blocked-by: ["52"]
```

Rules:

- The ticket body is the complete contract. A worker never needs chat history to
  do it. If it does, the ticket is not ready.
- Ticket bodies stay under ~150 lines. Longer contracts split.
- Workers never edit ticket frontmatter and never self-certify. State moves only
  by the transitions in 6.2.

### 5.4 The ledger (`NOTES.md`)

Entry format:

```markdown
## [L212] 2026-11-12T09:25Z arch1: PLE projection done (1188184e)
<prose. measurements with commands and settings, rulings, incidents.>
Supersedes: [L198]
```

Append-only. UTC from `date -u`, never local time relabeled. Entry ids are
monotonic and never reused.

### 5.5 The pinfile (frozen gates)

`gates/pins.toml` maps each gate script to its sha256. A gate is *frozen* when its
hash is in the pinfile. Frozen gates:

- are never edited to change a threshold;
- are verified by hash before every run that will be quoted as a pass;
- read only declared evidence paths and emit pass/fail; they never run the thing
  under test.

Changing a gate requires a maintainer decision, a new pin, and a ledger entry.
Quoting a rate or pass from a run of an unpinned or hash-mismatched gate is a
conformance failure.

### 5.6 Holdout scenarios

Borrowed directly from StrongDM's scenario testing, adapted for a small fleet.

- A scenario is an end-to-end description of observable behavior, written in prose
  plus a machine-checkable predicate, stored in `scenarios/` **outside the repo
  and outside every path an implementer-role session reads**.
- Implementer tickets may reference a scenario by id. They may not contain its
  predicate. The acceptance block of a ticket may contain regression checks the
  implementer must pass; it may not contain the holdout checks.
- The leak that matters is not the ticket, it is the message. Dispatch prompts,
  ledger entries, and review verdicts cite scenario ids, never predicate text.
  A dispatch that quotes an assertion to the implementer has burned the
  scenario no matter where the file lives.
- Contamination is terminal. A scenario whose predicate has appeared in any
  implementer-visible path is retired and rewritten, not scrubbed. The ledger
  is append-only, so old leaks stay in it; they mark the scenario dead, they
  do not mark the ledger wrong.
- The reviewer and approver read scenarios. A ticket closes only when its holdout
  scenarios pass, run by a role that did not write the code.
- For stochastic or performance behavior, acceptance is **satisfaction**: the
  fraction of sampled runs meeting the predicate, compared against a floor.
  Boolean green from a single sample is not acceptance.

On a single-human box, "outside the read path" is enforced by directory location
plus the dispatch rule that implementer prompts enumerate the files they may read.
It is convention, not sandboxing. State that honestly in the repo's binding rather
than pretending to an isolation you do not have.

### 5.7 The board tool

One command, `codic board`. It regenerates L1 and the Census section of L0 from:
the state directories, the ticket frontmatter, the gate results directory, and
the resource marker. It:

- parses every ticket or fails naming the file;
- enforces the token budgets of 4.2;
- refuses to run if a ticket file sits in an unknown directory;
- writes via tmp+rename.

## 6. Protocols

### 6.1 Agent boot and recovery

Every role session, on start and after any compaction or amnesia:

1. Read `STATE.md` in full.
2. Load the role's declared skill set (4.4).
3. Read the L1 rows for the ticket ids it was handed.
4. Expand L2 only for those ids.

Steps 1 and 2 together are the whole orientation. If either is insufficient to
act correctly, that is a defect in L0 or in the skill set, and fixing it is
itself a ticket.

No agent is ever oriented by a summary of prior chat. If L0 is insufficient to
act correctly, that is a defect in L0, and fixing it is itself a ticket.

### 6.2 Ticket lifecycle

```
ready -> doing        orchestrator admits; worktree exists; gate label warm
doing -> review       implementer files evidence, never moves the file itself;
                      reviewer or orchestrator moves it after evidence lands
review -> reviewed    reviewer's written verdict (accept or reject + findings)
reviewed -> gpu|done  approver moves; gpu only if the ticket declares resource: gpu
gpu -> done           evidence passes the frozen gate or the ticket's acceptance
any -> blocked        with a ledger entry naming what unblocks it
done -> (archived)    law and ledger keep the residue; the tree stays small
```

Rejection keeps a ticket out of any exclusive-resource window. A reviewer
rejection is terminal for that attempt: back to `doing` with the findings, not to
a window.

`blocked-by` entries are ticket ids or `resource:<name>`, so "the GPU is held by
a maintainer experiment" is representable state rather than an informal pause;
the Census names the current holder of each declared resource (4.2).

### 6.3 Supersede protocol

When any ruling, policy, or documented fact changes:

1. Append the new entry to the ledger, citing `Supersedes: [Lxxx]`.
2. Edit the affected Law line in `STATE.md` in place, citing the new entry.
3. If the change touches a frozen gate or this spec, require maintainer.

Nothing is deleted from the ledger. Nothing stale survives in Law.

### 6.4 Exclusive-resource windows

Generalized from the reference fleet's GPU window. Wherever the repo declares a
scarce exclusive resource (GPU, staging environment, paid API quota, license seat):

- One marker directory means the window is open. Admission is marker presence and
  the live state of the resource. Never a heuristic like free memory.
- Only one tool creates the marker. Everything else refuses while it exists.
- The window tool builds and syncs everything it can *before* taking the marker,
  while the resource still serves everyone else.
- A watchdog restores the resource on caller death and leaves a `force-restored`
  marker that the caller must check before quoting any number taken after it.
- A step that ran and returned nonzero is a result, not a lost window. Lost-device
  and negative-result get different exit codes and different log lines. Conflating
  them is how a correct negative result gets retried into the ground.
- Workers never touch the resource. They file a request in the `gpu/`-equivalent
  directory; the orchestrator runs windows.

### 6.5 Wake and addressing

- Long jobs run detached from every agent session (setsid, systemd, container).
  No agent session is a job supervisor.
- Wake registration happens before launch. The launcher records the wake target
  by name and refuses to start the job if the name does not resolve through the
  harness. `codic check` verifies every roster name resolves and every running
  detached job has a registration (I10). A job whose wake target cannot be
  named is a job nobody will hear from, which is the lost-wakeup incident in
  advance.
- On completion the job wakes the responsible role **by name** (R2). The wake
  message states what finished and where the evidence is, in one line.
- A wake is a nudge, not a state store. The job also writes its result to a
  file the agent reads on boot, so a dropped wake delays orientation instead
  of destroying it.
- An agent that must wait for a detached job ends its turn. Waiting in-session is
  forbidden; it burns context and dies with the session.

### 6.6 Budget the writes

The largest live context sink is not the state files, it is what agents write to
each other. One implementer session compacted at 207K tokens on 2026-11-12, and
the dispatches feeding it were re-pasted briefs.

- A dispatch is: ticket id, the delta since the last dispatch, and the budget
  declaration (which model, which slots it may spend). The ticket is the
  contract (5.3); re-pasting it into the prompt creates a second, drifting copy
  of the contract and is forbidden.
- Wake messages are one line (6.5). Verdicts land in evidence files, not in the
  prompt that announces them.
- Dispatch templates are generated from ticket frontmatter and capped in size
  (I11). A template that embeds a ticket body or a scenario predicate fails the
  check.

### 6.7 Merge queue

Parallel implementers land on one main. Two merges racing is how the second
inherits the first's breakage, so landing is serialized.

- The queue is tickets in `reviewed` that declare `worktree:`, ordered by
  ticket id.
- `codic merge next` takes the head: it takes `state/merge.lock` (holder pid
  and ticket inside; a lock whose pid is dead is stale and is replaced with a
  warning), resolves the worktree's branch, merges it into the current branch
  with `--no-ff`, and appends a ledger line naming ticket, branch, and result
  commit.
- On conflict the merge is aborted, the lock released, and the command exits
  with a diagnostic: resolution happens in the worktree, then `next` runs
  again.
- Merging does not move the ticket. Only the approver moves tickets to `done`
  (R1).
- `codic merge status` shows the queue and the lock.

## 7. Invariants

Machine-checkable. `codic check` (8) enforces all of them.

- I1  Law ≤ 2,048 tokens; Census ≤ 1,024; L1 ≤ 8,192.
- I2  Every Law line cites a ledger id that exists.
- I3  Ledger is append-only: the tool verifies the file's prefix hash chain
      against the last recorded checkpoint before regenerating anything.
- I4  Every ticket parses; every ticket sits in a known state directory; every
      frontmatter field is in schema.
- I5  Every frozen gate matches its pin.
- I6  No script or dispatch template addresses an agent by pane id or pid.
- I7  Every `done` ticket has a reviewer verdict and, if `resource: gpu`, a
      window evidence directory.
- I8  No implementer-visible path contains a holdout predicate: ticket read
      paths, the ledger, and the dispatch templates are all grepped against
      `scenarios/`. The ledger check applies to entries appended after a
      scenario's designation date; earlier leaks retire the scenario (5.6).
- I9  Census counts equal directory counts.
- I10 Every roster name resolves through the harness, and every running
      detached job has a wake registration.
- I11 Dispatch templates are generated from ticket frontmatter, within budget,
      and contain no scenario predicates.
- I12 Every role has a declared skill set within budget, and every law line
      carries a citation, an owner tag, and a counterexample clause.
- I13 Two in-flight tickets (`doing` or `review`) must not have intersecting
      `files:` write scopes, directory prefixes included. Overlapping scopes
      are a collision at merge time; fail at dispatch time instead.
- I14 Every `done` ticket's verdict records the exact commit it reviewed
      (`commit: <sha>`), and that commit exists in the repository. A verdict
      on a stale commit is a verdict on code that never shipped.
- I15 When `[review] cross_family` is enabled, the verdict's `model:` family
      must differ from the ticket's dispatched `model:` family. Fleets with
      access to one model family opt out and keep same-family review from a
      fresh session; the verdict still names its model.

## 8. `codic check`

One command, run by CI and by `codic board` before publishing L0.
It enforces I1 through I15 and exits nonzero on any violation. This is the
Atelier lesson generalized: the seam between "what the generator assumes" and
"what the files actually look like" is where fleets die, so make the seam a
command. A schema mismatch that surfaces after a 25-minute exclusive-resource
blackout costs the scarcest thing the fleet has; the same mismatch caught by
`codic check` costs nothing.

## 9. Portability

The pattern is repo-agnostic by construction. What follows is the honest split.

### 9.1 Generic core (transfers unchanged)

The pyramid and its budgets (4.2), law/ledger separation and supersede protocol
(4.3, 6.3), ticket-as-complete-contract with directory-as-state (5.3, 6.2), role
separation and the no-self-acceptance rule (4.1), frozen gates with a pinfile
(5.5), holdout scenarios and satisfaction acceptance (5.6), boot-from-disk
recovery (6.1), named agents and detached jobs (6.5), and the conformance checker
(8). None of this mentions GPUs, Rust, or any particular project.

### 9.2 Per-repo bindings (each repo supplies these)

| binding | reference fleet | a webapp's plausible value |
| --- | --- | --- |
| exclusive resource + window tool | the GPU, a window tool | staging env, or none |
| frozen gates + pins | `bench-gate.sh` | e2e suite, load test |
| role-to-model mapping | the agent CLI's own config | provider config in codic.toml |
| harness addressing | Herdr pane names | tmux, k8s jobs |
| scenario store | a path outside the repo | any non-repo path |
| ledger/board location | a queue dir outside the repo | `.codic/state/` in repo |
| role skill sets | per-role skill files, declared and budgeted | `state/skills/<role>.md` |
| external strategy approver | an out-of-band second opinion that survives blackouts (observation is never a grant) | optional; only where a scarce resource makes ordering decisions worth a second opinion |

### 9.3 Porting checklist

1. Create the state directories and move state out of the tracked tree if the repo
   treats run records as noise.
2. Install codic (`git clone … .codic && .codic/bin/codic init`). Budgets and
   invariants are not configurable per repo; that is the point.
3. Pin the gates you already trust. Everything unpinned is provisional until pinned.
4. Write the first Law file by hand, once, from the current rulings only. Cite
   whatever history exists even if ids are retroactive. Give every line its
   counterexample clause.
5. Declare each role's skill set in one budgeted file and put it in the boot
   sequence. Harvest the lessons your sessions currently re-derive.
6. Name every agent pane/session. Fix every script that addresses by id.
7. Move acceptance predicates the implementer must not see into `scenarios/`.
   Start with the two or three that actually gate releases.
8. Run `codic check` in CI. A fleet that cannot pass its own checker is not
   running this pattern, it is running vibes.

### 9.4 Known limits of the pattern

- Single-human boxes: holdout isolation is convention, not enforcement (5.6).
- Sub-second feedback loops need no windows at all; skip 6.4 entirely rather than
  building ceremony for a laptop.
- The pattern does not make a bad ticket contract executable. It makes an
  incomplete contract visible at admission instead of at hour nine.
- Budgets force compression, and compression can drop a load-bearing nuance.
  Expansion-by-citation only helps an agent that knows what it is missing, and
  the whole failure is that it does not. The mitigation is therefore not the
  citation but the counterexample clause (4.2): law carries the shape of its
  own misreading, and a ruling too big for that moves to a skill or a gate. A
  budget that forces law to be complete-or-promoted is the point; a budget
  that only forces it to be short is a shorter way to fail.

## Annex B. Lineage of each mechanism

| mechanism | origin |
| --- | --- |
| Pyramid Summaries, zoom levels | StrongDM Techniques page, adapted from pyramid TIFF / map tiles |
| scenarios as holdout, satisfaction | StrongDM, citing Cem Kaner's scenario testing (2003) |
| filesystem as memory, directories as state | StrongDM "The Filesystem" technique; already the reference fleet's practice |
| machine-checkable seam as a command | Atelier's `check:contract`, generalized |
| detached job + named wake | the reference fleet's window postmortems, 2026-11-11/12 |
| admission by marker presence, never memory floor | the reference fleet's hard-kill incident (350 MiB margin against an 89 GB pinned engine) |
| result vs lost-device separation | windows that retried correct negative results |
| boot-from-disk recovery | a retired harness's runbook: "recovery is never memory" |
| skill layer bound to roles, not sessions | the reference fleet's orchestrator review of draft 1; existing per-role skills practice |
| counterexample clause in law | the delegation rule that needed it: the named trap is what makes the rule load-bearing |
| wake registration before launch | the reference fleet's lost-wakeup incident, 2026-11-12 |
| dispatch = ticket id + delta | the reference fleet's 207K-token compaction, orchestrator report 2026-11-12 |
| contamination retires the scenario | standard holdout hygiene, applied after a dispatch leaked a predicate |
