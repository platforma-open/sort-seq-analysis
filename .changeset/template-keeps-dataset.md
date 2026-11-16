---
"@platforma-open/milaboratories.sort-seq-analysis.kind": minor
"@platforma-open/milaboratories.sort-seq-analysis.model": patch
---

Keep the dataset and the run recipe in a project template. A project made from a template came with Sort-Seq Analysis without its dataset, so the block could not run, and with its exclusions, read floor, gate order flag, input and baseline back on their defaults. The kind now carries all of them, and the block made from a template points at the columns of the project being made.
