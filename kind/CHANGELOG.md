# @platforma-open/milaboratories.sort-seq-analysis.kind

## 1.0.1

### Patch Changes

- d3a1dba: Migrate to the latest block template and declare the block kind.

  Adds the mandatory `kind/` package with the block's init-params contract: the condition, gate
  and sort-fraction column refs, the gate ladder, and the value snapshots a template needs to
  arrive runnable. The model is built with the kind and projects the same fields back out
  through `templateParams`.

  Also takes the block through the canonical SDK upgrade — model/ui-vue 1.83.x, workflow-tengo
  6.8.3, tengo-builder 4.0.23, block-tools 2.14.3.
