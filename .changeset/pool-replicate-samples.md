---
'@platforma-open/milaboratories.sort-seq-analysis.software': patch
'@platforma-open/milaboratories.sort-seq-analysis.model': patch
'@platforma-open/milaboratories.sort-seq-analysis.ui': patch
'@platforma-open/milaboratories.sort-seq-analysis.block': patch
---

Pool replicate samples instead of refusing the run

A condition-and-gate group holding more than one sample used to fail the run. Its reads are
now summed, matching what `titeseq-analysis` and `clonotype-enrichment` already do.

The pooling is reported rather than silent, which is the objection the original refusal was
raised against: the manifest gains a `pooledGroups` list, the run log names every merged
group and its samples, and the Run statistics dialog shows a warning listing them. The dialog
resolves sample ids to sample labels through the sample axis's label column, so the alert
names samples the way the user does. Only retained conditions are reported — an excluded
condition is not part of the run. Where replicates supplied different sort fractions, the
non-null values are averaged and that is flagged separately.

Two things broke quietly on replicate samples and are fixed at the source, by pooling before
anything reads the table: the read-distribution file emitted duplicate `(variantKey, gate)`
keys, and the sort-fraction check counted a twice-collected gate's fraction twice and refused
runs that were entirely valid.

This is temporary. It does not decide whether replicates should be pooled at all rather than
scored separately, nor what to do when they disagree on the sort fraction.
