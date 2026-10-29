---
"@platforma-open/milaboratories.sort-seq-analysis.block": minor
"@platforma-open/milaboratories.sort-seq-analysis.model": minor
"@platforma-open/milaboratories.sort-seq-analysis.ui": minor
"@platforma-open/milaboratories.sort-seq-analysis.workflow": minor
---

Update the SDK and accept a subset filter (e.g. a Repertoire Labeling label) with the input dataset. The dataset list is built with buildDatasetOptions (requireEnrichments: false). The subset restricts the reads before the analysis, so gate frequencies, enrichments and mean bins are computed within the subset and differ from a full-data run; if the parent variant is outside the subset, Mean bin vs parent and the wild-type baseline are not produced. Outputs of a subset run carry pl7.app/inputSubset in their domain and a trace rooted in the subset, so their labels name it. Unfiltered runs are unchanged.
