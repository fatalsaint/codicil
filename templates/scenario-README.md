# Holdout scenarios (SPEC 5.6)

One file per scenario: `S<NN>.md` with `id:`, `title:`, `status: active|retired`,
`designated: YYYY-MM-DD`, prose, and the machine-checkable predicate inside a
```predicate fence.

Rules that `codic check` I8 enforces:

- Tickets and dispatches cite scenario ids, never predicate text.
- A predicate must not appear in implementer-visible paths (queue/, dispatch/,
  the implementer skill, or ledger entries appended after designation).
- Contamination is terminal: `codic scenario retire <id>`, then rewrite under a
  new id. Never edit a contaminated predicate in place.
- For stochastic or performance behavior, acceptance is satisfaction: the
  fraction of sampled runs meeting the predicate, against a floor. A single
  green sample is not acceptance.

Keep this directory outside every path an implementer session reads whenever
the repo can afford it (`[codic] scenarios_path` in codic.toml).
