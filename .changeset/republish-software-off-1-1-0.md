---
'@platforma-open/milaboratories.sort-seq-analysis.software': patch
'@platforma-open/milaboratories.sort-seq-analysis.workflow': patch
'@platforma-open/milaboratories.sort-seq-analysis.model': patch
'@platforma-open/milaboratories.sort-seq-analysis.ui': patch
'@platforma-open/milaboratories.sort-seq-analysis.block': patch
---

Republish the software package off version 1.1.0

The binary registry already held `software/.../main/1.1.0.tgz`, uploaded on 13 August from a much
older source tree. The 1.1.0 release did not replace it, so the block paired its new workflow with
that old Python and every run failed with `unrecognized arguments: --positions --parents`.

No behaviour changes. This moves every package to 1.1.1, which is free on both registries.
