<!-- BEGIN codic -->
## Codic harness

This repo runs the codic harness in `{dir}/` (gitignored; its state tree has its own git history).

Boot rule: a codic session orients from `{dir}/state/STATE.md` plus its role skill in
`{dir}/state/skills/<role>.md`, never from a chat transcript. Tickets live in
`{dir}/state/queue/<state>/`; the ledger is `{dir}/state/NOTES.md`. Tools: `{dir}/bin/codic`
(board, check, ticket, dispatch, launch, run). Invariants: `{dir}/SPEC.md` section 7;
`codic check` must be green before merges.
<!-- END codic -->
