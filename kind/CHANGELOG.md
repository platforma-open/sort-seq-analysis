# @platforma-open/milaboratories.sort-seq-analysis.kind

## 2.0.0

### Major Changes

- 04203fc: Columns are stored by their result-pool column ids: the dataset and the condition, gate and sort-fraction columns. The gates of the gate order, the unsorted input and the excluded conditions are stored as column value references of the gate and condition columns, so the block that produced the metadata knows which of its values this block uses; the ranks the workflow receives are keyed by the same references. The model finds columns and builds the options of every column picker through the column collection API instead of the deprecated result pool API, and the workflow takes every column through a column bundle. The model gives the value options of each metadata column on offer, and the settings panel reads the values through them, so a column of any storage format can be picked from; a picked column whose values cannot be read, or that its block no longer produces, says so under its picker. The run statistics take the sample names from the model. The snapshots of the gate and condition columns' values, written when a column is picked, are stored as column value references of that column too.
  Opening a project created before this change keeps its dataset, and clears its condition, gate and sort-fraction columns, the gate order, the unsorted input, the excluded conditions and the value snapshots, since they were stored by ids anchored to the dataset and as plain values, which name no producing block. The condition and gate columns have to be picked again before the block runs; picking the gate column seeds the gate order with every value of that column, so gates removed from the order before have to be removed again. The sort-fraction column, the unsorted input and the excluded conditions are optional, so the block runs without them: until they are picked again, the scores are not corrected for sort yield, no enrichment against the input is computed and every condition is scored. The initialization params of the kind carry the same ids and references, the value snapshots included, so templates made for an earlier version of the kind cannot be applied.
  Gates, the input and excluded conditions that are no longer among the values of their column stay selected and are marked as not available instead of being removed silently, with a tooltip naming the block that was to provide them, as a link to it, and what went wrong. Picking another gate or condition column still resets the values picked in it and rewrites its snapshot. No check that disables the run is removed: a gate column with no values, a gate or an input the gate column does not carry, and every condition excluded still disable it.

## 1.0.1

### Patch Changes

- d3a1dba: Migrate to the latest block template and declare the block kind.

  Adds the mandatory `kind/` package with the block's init-params contract: the condition, gate
  and sort-fraction column refs, the gate ladder, and the value snapshots a template needs to
  arrive runnable. The model is built with the kind and projects the same fields back out
  through `templateParams`.

  Also takes the block through the canonical SDK upgrade — model/ui-vue 1.83.x, workflow-tengo
  6.8.3, tengo-builder 4.0.23, block-tools 2.14.3.
