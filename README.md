# sort-seq-analysis

**Sort-Seq Analysis** — a Platforma block that scores protein variants from a sort-seq (FACS bin)
experiment. Per condition it emits the read-weighted mean of the gate ranks each variant sorted into
(`pl7.app/facsBin/gateRankMean`) and that value minus the parent's (`pl7.app/facsBin/binScore`).

## Specification

`docs/text/work/projects/sequence-repertoires/facs-bin-analysis/` in the `docs/text` repo.

- `README.md` — the front door: what the block is for and what always holds.
- `implementation.md` — the implementer's door: the decisions and why each is held.
- `work/atoms/` — the spec source. Never hand-edit the two rendered docs above.

Cross-block contracts this block honours rather than decides live in the umbrella spec,
`docs/text/work/projects/sequence-repertoires/dms-analysis/`.

## Layout

| Path | What |
|---|---|
| `model/` | `BlockModelV3` — args projection, outputs, sections |
| `workflow/` | Tengo template — resolves inputs, invokes the computation, builds the output columns |
| `ui/` | Vue 3 UI — settings drawer and result views |
| `software/` | Python package holding the score computation |
| `block/` | Published facade — block meta and components |
| `test/` | Integration tests against a running backend |

## Build

```bash
pnpm install
pnpm build:dev-local     # local software paths; there is no plain `build` script
```

The layout is owned by `block-tools structure`. To take an SDK upgrade, run `pnpm upgrade-sdk` — do not
hand-edit tsconfigs, turbo config, lint config or the catalog.
