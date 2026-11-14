# Operating and migrating to the fleet pattern

Companion to SPEC.md (draft 2). Part 1 is how a fleet running this pattern is
set up and used day to day. Part 2 is the concrete migration of the live Ninox
fleet, step by step, with the exact commands for this box.

---

## Part 1. Setup and daily use

### The mental model, in one paragraph

The maintainer owns goals, gates, and law. The orchestrator owns tickets,
resource windows, and operational law. Everything any session needs to act
correctly is on disk, and every session boots from disk instead of from a
transcript. The human's daily interface is one small file (`STATE.md`) and one
named agent (`orchestrator`). If the human has to explain something twice, the
pattern is broken somewhere: the fact belongs in Law, a skill, a ticket, or the
ledger, and until it is written there it is an unversioned ruling that dies with
the session that heard it.

### One-time setup for a new repo

1. **State directory.** Pick a location: `.fleet/` inside the repo if run
   records are welcome in history, outside it (like `~/<repo>-ops/`) if not.
   Create the state dirs: `ready/ doing/ review/ reviewed/ gpu/ blocked/ done/`.
2. **Version it.** `git init` the state directory if the repo doesn't already
   track it. The append-only ledger is only as trustworthy as its history, and
   you need rollback points for every later step. Gitignore the bulk
   (evidence, corpora).
3. **Tools.** Write `fleet-board` (regenerates L1 + Census, parses every ticket
   or fails, enforces budgets, tmp+mv) and `fleet-check` (enforces I1-I12).
4. **Pin the gates you trust.** `gates/pins.toml` with sha256 per gate script.
   Everything unpinned is provisional.
5. **Write Law once, by hand.** 10-20 lines from current rulings only. Each
   line: imperative, addressee role, ledger citation, owner tag, counterexample
   clause.
6. **Declare role skills.** One budgeted file per role. Harvest the lessons
   sessions currently re-derive.
7. **Name every agent.** Fix every script and template that addresses by pane
   id or pid.
8. **Scenarios.** `scenarios/` outside the read path, starting with the two or
   three predicates that actually gate releases.
9. **CI.** `fleet-check` runs on every push. Red check, no merges.

### The daily loop (maintainer)

- **Read** `STATE.md`. Two minutes. Census gives queue counts, gate rows with
  live numbers, the critical path, resource holders, and the roster. That is
  the whole status meeting.
- **Drill down** only when a row interests you: the BOARD line, then the ticket.
- **Decide** by editing your Law lines and appending a ledger entry. That is
  the mechanism for changing policy; it needs no chat with anyone.
- **Direct** with one line to the orchestrator:
  `herdr agent prompt orchestrator "<what you want, and why>"`.
  It boots from disk and already knows the rules.
- **Verify** with `fleet-check; echo $?`.
- **Approve** nothing routine. The approver role moves tickets to done. You
  move Law, gates, goals, and scenarios.

### Who touches what

| role | writes |
| --- | --- |
| maintainer | own Law lines, gates + pins, scenarios, goals, human-queue |
| orchestrator | tickets, its own operational Law lines, ledger, window records, dispatches |
| architect | ticket contracts |
| implementer | its worktree, its evidence directory |
| reviewer | evidence and verdict files, never tickets |
| approver | ticket state transitions to done |
| fleet-board | L1 and the Census section, nothing else |

### Rules of thumb for the human

- Never paste context into an agent session. If an agent needs to know
  something, it belongs in Law, a skill, a ticket, or the ledger.
- Never quote a rate or pass from an unpinned gate run.
- Read `STATE.md` before intervening. Don't intervene from transcript memory;
  that is how the orchestrator got its disease.
- Your scarce resource is decisions, not information. L0 exists so you spend
  decisions only on changes.
- When a fresh session acts wrongly, fix the file it read, not the session.

### Interacting via Herdr (this box)

```bash
herdr agent list                                  # roster + live status
herdr agent prompt orchestrator "one line"        # direct work
herdr agent prompt orchestrator "..." --wait      # ask and block for the answer
herdr agent read orchestrator --source recent --lines 50   # audit what it saw
herdr agent get impl2                             # is it alive, what state
```

Never `herdr pane send-text w1:p1 ...`. Pane ids break on layout changes; names
are the contract (SPEC R2, I10).

---

## Part 2. Migrating the live Ninox fleet

Constraints honored: the fleet keeps working throughout; every step is CPU-side
and needs no device window; each step verifies independently; the only
destructive step is last and reversible. Run the migration itself as a ticket
(`130-fleet-migration`) so the pattern is exercised by the act of adopting it.

### Step 0. Version the state tree

`~/ninox-ops` is not a git repo. The ledger has no history and the migration has
no rollback point. Fix that first.

```bash
cd ~/ninox-ops
git init
printf 'evidence/\ncorpora/\nhalogen-baseline/\nwork/\ndive/\nprobes/*.log\n' > .gitignore
git add -A && git commit -m "fleet migration: snapshot pre-L0 state"
```

Verify: `git log --oneline -1` exists; `.git` stays small (evidence stays out).

### Step 1. Ledger entry ids

The ledger has 7 `##` sections and 281 timestamped `- 2026-...` bullets, none
with ids, so Law cannot cite them. One-time renumber in file order: sections and
bullets get `[L1]`, `[L2]`, ... monotonically. Then append the migration entry
itself, which is the first entry that must not be renumbered later.

```bash
# awk pass: prefix each '^## ' and '^- 2026-' line with the next id
awk '/^## |^- 2026-/ { printf "[L%d] ", ++n } { print }' NOTES.md > NOTES.md.new
mv NOTES.md.new NOTES.md
```

(Review the diff before committing; the script is mechanical but the ledger is
the audit trail of record.)

Verify: ids strictly monotonic; `grep -c '^\(- \|## \)\[L' NOTES.md` = 282 + 1
migration entry. From now on, append-only is enforced by fleet-check's prefix
hash chain (I3), not by politeness.

### Step 2. Write `STATE.md` Law (judgment step)

Owner: orchestrator drafts, maintainer approves and owns the class lines.
Harvest current rulings from NOTES, `AGENTS.md`, and `orchestration.md`; 15-20
lines; each with citation, owner, counterexample. The known load-bearing ones:

- gates are law, hash-pinned, never quote an unpinned or profiled rate
- device admission is marker presence and engine state, never a memory floor
  (counterexample: the 350 MiB hard-kill)
- delegation budget trap (`task` is default and local; name the model class in
  every dispatch)
- workers never touch the device; requests go in `queue/gpu/`
- never write under `work/` from a slice worktree (purge rule 55d18c8)
- reviewer rejection keeps a ticket out of a window
- timestamps are `date -u` verbatim
- dispatch = ticket id + delta + budget declaration, never a re-pasted brief

Verify: Law ≤ 2,048 tokens; every line has `[Lxxx]`, owner tag, counterexample.

### Step 3. Replace `nx-board` with `fleet-board`

Changes from the current script:

- parse both ticket formats (frontmatter and prose); on a ticket that yields
  neither role nor question, fail naming the file instead of printing `?`
- emit two artifacts: `BOARD.md` (L1, budget 8,192) and the `## Census` section
  of `STATE.md` (budget 1,024), both tmp+mv
- Census carries: queue counts, gate rows, critical path, resource holders
  (including `resource:apu` held by maintainer experiment), roster with wake
  registrations
- exit nonzero on any budget violation

Verify: run it; zero `?` rows or a named failure; budgets enforced by a
deliberate overflow test.

### Step 4. `fleet-check` v1

Implement now: I1 budgets, I2 citations exist, I4 every ticket parses and sits
in a known state dir, I5 gate pins (create `gates/pins.toml` with
`perf-baseline.sh` sha256 `61e4a04...c507e`), I6 no pane-id addressing in
scripts/templates, I9 census counts equal directory counts, I10 roster names
resolve via `herdr agent get`, I12 law-line shape and skill declarations.
Defer to v2 (they need artifacts that don't exist yet): I3 prefix chain, I8
predicate grep, I11 template cap.

Verify: green on the migrated tree; then break one invariant on purpose and
confirm red.

### Step 5. Name the orchestrator pane

```bash
herdr agent rename w1:p1 orchestrator
herdr agent get orchestrator        # must resolve now
```

Then replace every `herdr agent prompt w1:p1` in `orchestration.md`, driver
templates, and window scripts with the name. The wake path is the fleet's
single point of failure and today it points at a layout accident.

Verify: `grep -rn 'w1:p1' ~/ninox-ops ~/ninox/scripts` returns nothing.

### Step 6. Declare role skills

Create `~/ninox-ops/skills/{orchestrator,implementer,architect,reviewer}.md`,
each budgeted (1,500 tokens is a reasonable start). Harvest from
`~/ninox-ops/notes/`, the memory store, and the runbook:

- **orchestrator**: delegation budget trap; window protocol incl. watchdog and
  force-restored semantics; admission rule; dispatch discipline (6.6);
  blocked-by resource markers
- **implementer**: gate recipe and label/warm-target contract; worktree and
  purge rules; never-GPU rule; engine-answering rule before ending a turn
- **architect**: contract authoring rules; the rev-checklist lessons (hash
  amendments, exact semantics, no chat-summary counts)
- **reviewer**: reference-comparison rule (file and line, mechanism difference,
  never "the reference is faster"); honest-negative reporting format

Verify: fleet-check I12.

### Step 7. Scenarios

```bash
mkdir -p ~/ninox-ops/scenarios
```

Seed three: S1 the frozen gate itself (predicate already lives in the pinned
script); S2 block-parity per-token match against FP32 reference logits; S3 the
`pp@32768` row shape (`output_tokens == 128`, full-length prompt). Predicates
live only here; tickets and dispatches cite `S1`-style ids. Any scenario whose
predicate already leaked into implementer-visible history (the case-26 class) is
retired and rewritten, not reused.

### Step 8. Runbook and AGENTS.md (the only destructive step)

After Law and skills absorb HANDOFF and the runbook:

- rewrite `agents/orchestration.md`: delete the 23 dead `scripts/nx`
  references, boot protocol becomes STATE.md + role skills, tools are
  fleet-board/fleet-board/nx-window family
- update `AGENTS.md`: boot rule cites the boot sequence; supersede protocol
  referenced
- move `HANDOFF.md` to `archive/` only after diffing it: every fact in it must
  now live in Law, a skill, a ticket, or the ledger. Anything missing gets
  written first. This is the migration's completeness test.

Verify: `grep -c 'scripts/nx \|nx run\|nx queue' agents/orchestration.md` = 0;
HANDOFF absorbed-and-archived recorded as a ledger entry.

### Step 9. Cutover (no flag day)

There is no switch. The next orchestrator, arch, or rev session boots per the
updated `AGENTS.md` from STATE.md + skills; running sessions finish their
tickets on the old reading list. The migration is complete when a fresh session
acts correctly on L0 + skills alone. Every time one doesn't, that is a defect in
a file, and the fix is a Law edit, a skill edit, or a ticket, never a longer
prompt.

### Ownership and order

| step | who | when |
| --- | --- | --- |
| 0, 1 | mechanical (this session can do it) | first, always |
| 2 | orchestrator drafts, maintainer approves | after 1 |
| 3, 4 | mechanical | after 1, parallel with 2 |
| 5 | mechanical | anytime |
| 6 | role owners draft, maintainer approves | after 2 |
| 7 | maintainer decides predicates | anytime |
| 8 | mechanical after 2+6 absorb the old text | last |
| 9 | automatic | follows |

The whole migration is CPU-side. It needs no window, stops no engine, and the
fleet's next device run is unaffected.
