# Codicil

A state architecture for fleets of coding agents. Clone it into any repository
as `.codic/`, gitignore it, and every agent session boots from disk instead of
from a transcript.

A codicil is the legal instrument that changes a ruling while the archive keeps
the superseded text. That is exactly what this is: current law lives in one
small curated file, every superseded ruling stays in an append-only ledger, and
no agent session is ever oriented by a summary of prior chat.

`codic` is not an agent loop, not a task runner, and not a prompt library. It
answers three questions: what must an agent read when it starts, where current
truth lives so a superseded ruling can never be mistaken for an active one, and
who decides whether work is accepted so the party producing a result is never
the sole party judging it. The full spec is [SPEC.md](SPEC.md) (the spec's
`fleet-board`/`fleet-check` tools are implemented as `codic board`/`codic
check`); the day-to-day guide is [OPERATIONS.md](OPERATIONS.md).

## Install

```bash
cd /path/to/any/repo
git clone https://github.com/your-org/codic .codic
.codic/bin/codic init
```

`codic init` does five things:

1. Writes `.codic/codic.toml` (your bindings: coding agent, harness, per-role
   models and counts) from the annotated template.
2. Scaffolds the state tree under `.codic/state/`: `STATE.md` (L0 law +
   generated census), `NOTES.md` (append-only ledger, seeded with `[L1]`),
   `queue/{ready,doing,review,reviewed,gpu,blocked,done}/`, `skills/`,
   `gates/`, `scenarios/`, `evidence/`, `dispatch/`, `runs/`.
3. Gives `state/` its own git history. The ledger is only as trustworthy as
   its history, and the outer repo never sees any of it: init adds `.codic/`
   to the repo's `.gitignore`, so active worker and agent state stays out of
   the project's tracked tree.
4. Declares one budgeted skill file per role (`state/skills/*.md`).
5. Appends the boot rule to your `AGENTS.md`/`CLAUDE.md` if present (opt out
   with `--no-agents-md`), then runs `codic board` and `codic check`.

Requires Python 3.11+ (stdlib only, no install step). HERDR first: with
[herdr](https://github.com/your-org/herdr) in `PATH` you get named agents with
lifecycle states (`idle/working/blocked/done`); tmux is a degraded second;
`backend = "none"` keeps tickets, board, and check usable with no harness at
all.

## The shape of it

```
repo/
  .gitignore                  # contains: .codic/
  AGENTS.md                   # boot rule wired in by init
  .codic/                     # this repo, cloned; outer repo ignores it
    codic.toml                # your bindings (untracked by the harness repo)
    bin/codic                 # the CLI
    state/                    # own git history; bulk (evidence, runs) ignored
      STATE.md                # L0: ## Law (curated, ≤2048 tok) + ## Census (generated, ≤1024)
      NOTES.md                # ledger: append-only forever, [L1], [L2], ...
      queue/                  # directory IS state: ready doing review reviewed gpu blocked done
        BOARD.md              # L1: one row per ticket, ≤8192 tok, generated
      skills/<role>.md        # the skill layer: operational knowledge per role
      gates/pins.toml         # frozen gates: sha256 per gate script
      scenarios/              # holdout predicates, invisible to implementers
      evidence/ dispatch/ runs/ resources/
```

Three zoom levels. An agent boots at L0 plus its role skill and expands
downward by id, never sideways. Law is edited in place and cites the ledger;
the ledger is append-only and never edited. A ruling that changes gets a new
ledger entry with `Supersedes: [Lxxx]` and an in-place Law edit (SPEC 6.3).

## Config

`codic.toml` binds the pattern to your repo:

```toml
[harness]
backend = "herdr"        # herdr (first-class) | tmux | none
launch_mode = "pane"     # how new agents are placed: pane | tab | window

[coding_agent]
default = "omp"          # omp | claude | codex | opencode | your own launcher

[llm]
model = "..."            # fleet-wide default model
env = {}                 # provider env for launched agents

[agents.implementer]     # per agent type: count, coding agent, model, args
count = 3
agent = "omp"
model = "some-fast-model"
args = []                # extra native args; {model} is substituted

[agents.reviewer]
count = 1
agent = "claude"
model = "some-strong-model"

[agents.architect]
count = 1
```

`launch_mode` maps onto herdr topology: `pane` splits the calling pane, `tab`
creates a tab in the current workspace, `window` creates a workspace. Per-role
`model`/`agent` reach the launcher via its `model_flag`; `herdr_kind` gives
lifecycle-state recognition. Unknown coding agents are one table away:

```toml
[coding_agents.myagent]
launch = "myagent"
model_flag = "--model"
herdr_kind = ""          # "" -> launched as a plain command, no lifecycle states
```

## Daily loop

```bash
codic status                      # roster, resources, running jobs
codic ticket new 7 --role implementer --title "add retry to client" \
  --question "Does the client retry 503s with backoff?" \
  --file src/client.py --accept "pytest tests/test_retry.py"
codic ticket move 7 doing         # admit work
codic dispatch 7 --delta "first dispatch" --send impl1   # arms a 30-min silence watchdog
codic prompt orchestrator "why is ticket 7 still in doing?" --wait
codic watch arm impl1 --why "ticket 7"   # arm manually for any other waiting turn
codic watch cancel wd1763000000          # when the report lands
codic gate pin scripts/e2e.sh     # freeze a gate you trust
codic gate run e2e                # hash-verified before it may be quoted
codic run --wake orchestrator -- make -j8 bench   # detached job, wakes by name
codic ledger --title "window policy" --supersedes L4 --body "..."
codic board && codic check        # publish + enforce; CI runs check on every push
```

`codic check` enforces the twelve invariants (SPEC 7): budgets, citations,
ledger append-only via prefix hash chain, ticket schema, gate pins, no
pane-id/pid addressing anywhere (names are the contract, R2), verdicts on done
tickets, no holdout predicate in any implementer-visible path, census equals
directories, roster names resolve, dispatch templates generated and capped,
every law line carrying citation + owner + counterexample clause. A fleet that
cannot pass its own checker is not running this pattern, it is running vibes.

## Commands

| command | purpose |
| --- | --- |
| `init` | scaffold state, config, gitignore + AGENTS.md wiring |
| `board` | regenerate BOARD.md + Census; fails on unparseable tickets or budget violations |
| `check` | enforce I1–I12; exit nonzero on any violation |
| `status` | roster with live harness state, resources, detached jobs |
| `launch <role>` | start a named agent per config (mode, agent, model from codic.toml) |
| `prompt <name> <text>` / `read <name>` | dispatch and audit by name only |
| `stop <name>` / `forget <name>` | close a launched agent / drop a stale roster entry |
| `ticket new/move/show` | ticket lifecycle; directory move is the transition |
| `dispatch <id>` | generate the dispatch (ticket id + delta + budget, capped) and optionally send |
| `ledger` / `law add` | append ledger entries; append shape-checked law lines |
| `gate pin/check/run` | frozen gates with sha256 pins |
| `scenario new/retire/list` | holdout scenarios |
| `run --wake <name> -- <cmd>` | detached job with wake registration before launch |
| `watch arm/cancel/list` | silence watchdog: if an agent has not reported in 30 min, wake the orchestrator with its live state |
| `config` | print resolved config |

## Honest limits

- Single-human boxes: holdout isolation is directory location plus dispatch
  discipline, not sandboxing. `codic check` I8 greps for leaks; it cannot
  prevent an implementer from being shown a predicate in a prompt.
- Token budgets are enforced with a deterministic chars/4 estimate, not a
  model-specific tokenizer.
- Sub-second feedback loops need no resource windows; skip that ceremony.
- The pattern does not make a bad ticket contract executable. It makes an
  incomplete contract visible at admission instead of at hour nine.

## License

MIT. See [LICENSE](LICENSE).
