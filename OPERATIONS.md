# Operating and adopting the codic pattern

Companion to SPEC.md. Part 1 is how a fleet running this pattern is set up and
used day to day. Part 2 is how to migrate an existing repo (with an existing
pile of notes, handoffs, and ad-hoc state) onto the pattern without a flag day.

---

## Part 1. Setup and daily use

### The mental model, in one paragraph

The maintainer owns goals, gates, and law. The orchestrator owns tickets,
resource windows, and operational law. Everything any session needs to act
correctly is on disk, and every session boots from disk instead of from a
transcript. The human's daily interface is one small file (`STATE.md`) and one
named agent (`orchestrator`). If the human has to explain something twice, the
pattern is broken somewhere: the fact belongs in Law, a skill, a ticket, or the
ledger, and until it is written there it is an unversioned ruling that dies
with the session that heard it.

### One-time setup for a new repo

```bash
cd /path/to/any/repo
git clone https://gitea.linuxniche.com/FatalSaint/codicil.git .codic
.codic/bin/codic init
```

`codic init` scaffolds the state tree (`STATE.md` with seed law, `NOTES.md`
with entry `[L1]`, the queue directories, budgeted role skills, gates,
scenarios), writes `codic.toml` from the annotated template, gives `state/` its
own git history, adds `.codic/` to the repo's `.gitignore`, and wires the boot
rule into `AGENTS.md`/`CLAUDE.md`. Then, by hand:

1. **Write Law once.** Edit the seed lines into your repo's current rulings,
   10-20 lines. Each line: imperative, addressee role, ledger citation, owner
   tag, counterexample clause. `codic law add` enforces the shape.
2. **Harvest role skills.** The seeded `state/skills/*.md` are skeletons; fill
   them with the lessons your sessions currently re-derive.
3. **Pin the gates you trust.** `codic gate pin <script>`. Everything unpinned
   is provisional.
4. **Bind the harness.** `codic.toml`: backend (herdr first), launch mode
   (pane/tab/window), coding agent + model + count per role.
5. **Scenarios.** Seed the two or three predicates that actually gate
   releases, in `state/scenarios/` or a path outside the repo.
6. **CI.** `codic check` runs on every push. Red check, no merges.

### The daily loop (maintainer)

- **Read** `STATE.md`. Two minutes. Census gives queue counts, gate rows with
  live numbers, the critical path, resource holders, the roster, and armed
  watchdogs. That is the whole status meeting.
- **Drill down** only when a row interests you: the BOARD line, then the ticket.
- **Decide** by editing your Law lines and appending a ledger entry
  (`codic ledger --title "..." --body "..."`). That is the mechanism for
  changing policy; it needs no chat with anyone.
- **Direct** with one line to the orchestrator:
  `codic prompt orchestrator "<what you want, and why>"`.
  It boots from disk and already knows the rules.
- **Verify** with `codic check; echo $?`.
- **Approve** nothing routine. The approver role moves tickets to done. You
  move Law, gates, goals, and scenarios.

### Who touches what

| role | writes |
| --- | --- |
| maintainer | own Law lines, gates + pins, scenarios, goals |
| orchestrator | tickets, its own operational Law lines, ledger, window records, dispatches |
| architect | ticket contracts |
| implementer | its worktree, its evidence directory |
| reviewer | evidence and verdict files, never tickets |
| approver | ticket state transitions to done |
| supervisor | its own log and result files, nothing else |
| `codic board` | BOARD.md and the Census section, nothing else |

### Rules of thumb for the human

- Never paste context into an agent session. If an agent needs to know
  something, it belongs in Law, a skill, a ticket, or the ledger.
- Never quote a rate or pass from an unpinned gate run.
- Read `STATE.md` before intervening. Don't intervene from transcript memory.
- Your scarce resource is decisions, not information. L0 exists so you spend
  decisions only on changes.
- When a fresh session acts wrongly, fix the file it read, not the session.

### Interacting via Herdr

```bash
codic status                                  # roster + live status
codic prompt orchestrator "one line"          # direct work
codic prompt orchestrator "..." --wait        # ask and block for the answer
codic read orchestrator --lines 50            # audit what it saw
codic launch implementer                      # next free impl slot, per config
```

Under the hood these are `herdr agent ...` calls by name. Never address a pane
by id (`w1:p1`) in a script or prompt: pane ids break on layout changes; names
are the contract (SPEC R2, I6, I10).

---

## Part 2. Migrating an existing repo

Constraints honored: the fleet keeps working throughout; every step is
independently verifiable; the only destructive step is last and reversible.
Run the migration itself as a ticket so the pattern is exercised by the act of
adopting it.

### Step 0. Snapshot what you have

If the repo has an existing pile (handoff docs, notes ledgers, a runbook),
commit or copy it before touching anything. The migration needs rollback
points. `codic init` already versions the new state tree; the old pile stays
where it is until step 8 absorbs it.

### Step 1. Ledger entry ids

If an existing notes ledger exists, give its rulings and entries monotonic
ids so Law can cite them. One-time renumber in file order, then append the
migration entry itself — the first entry that must never be renumbered.

```bash
# awk pass: prefix each section/heading line of the old ledger with the next id
awk '/^## |^- 2026-/ { printf "[L%d] ", ++n } { print }' OLD_LEDGER.md > OLD_LEDGER.md.new
mv OLD_LEDGER.md.new OLD_LEDGER.md
```

Review the diff before committing; the ledger is the audit trail of record.
From now on, append-only is enforced by `codic check`'s prefix hash chain (I3),
not by politeness.

### Step 2. Write Law (judgment step)

Owner: orchestrator drafts, maintainer approves and owns the class lines.
Harvest current rulings from the old pile; 15-20 lines; each with citation,
owner, counterexample. The kinds of rulings that earn a Law line:

- gates are law, hash-pinned, never quote an unpinned or profiled rate
- admission to an exclusive resource is marker presence and live state, never
  a heuristic like free memory (give the incident that proved it)
- the delegation budget trap (name the model class in every dispatch)
- workers never touch the exclusive resource; requests go to the queue
- reviewer rejection keeps a ticket out of a window
- timestamps are `date -u` verbatim
- dispatch = ticket id + delta + budget, never a re-pasted brief

Verify: Law ≤ 2,048 tokens; every line has `[Lxxx]`, owner tag, counterexample
(`codic check` I1/I12).

### Step 3-4. Board and checker

`codic board` and `codic check` are the migration's instruments from day one:
board fails loudly on any legacy ticket it cannot parse (name the file, fix
the file), check goes red on every invariant break. Migrate legacy tickets to
frontmatter as they are touched; the I4 failure list is your work queue.

### Step 5. Name every agent

Fix every script and template that addresses agents by pane id or pid; replace
with names (`codic launch` assigns slots per `codic.toml`). The wake path is
the fleet's single point of failure and an id-addressed wake path points at a
layout accident.

Verify: `grep -rn 'w[0-9]:p[0-9]' <your scripts>` returns nothing; `codic check`
I6/I10 green.

### Step 6. Declare role skills

Fill the seeded `state/skills/*.md` from the old pile — the lessons sessions
currently re-derive. Typical harvest: window protocol and admission rules for
the orchestrator; gate recipe and worktree rules for the implementer; contract
authoring rules for the architect; reference-comparison and honest-negative
rules for the reviewer.

Verify: `codic check` I12.

### Step 7. Scenarios

Seed the two or three predicates that actually gate releases. Predicates live
only in `scenarios/`; tickets and dispatches cite `S1`-style ids. Any scenario
whose predicate already leaked into implementer-visible history is retired and
rewritten, not reused.

### Step 8. Absorb the old runbook (the only destructive step)

After Law and skills absorb the old handoff docs and runbook: archive them.
Every fact in them must now live in Law, a skill, a ticket, or the ledger.
Anything missing gets written first. This is the migration's completeness test.
Record the absorption as a ledger entry.

### Step 9. Cutover (no flag day)

There is no switch. The next orchestrator, architect, or reviewer session
boots per the wired `AGENTS.md` from `STATE.md` + skills; running sessions
finish their tickets on the old reading list. The migration is complete when a
fresh session acts correctly on L0 + skills alone. Every time one doesn't, that
is a defect in a file, and the fix is a Law edit, a skill edit, or a ticket,
never a longer prompt.

### Ownership and order

| step | who | when |
| --- | --- | --- |
| 0, 1 | mechanical | first, always |
| 2 | orchestrator drafts, maintainer approves | after 1 |
| 3, 4 | mechanical | after 1, parallel with 2 |
| 5 | mechanical | anytime |
| 6 | role owners draft, maintainer approves | after 2 |
| 7 | maintainer decides predicates | anytime |
| 8 | mechanical after 2+6 absorb the old text | last |
| 9 | automatic | follows |
