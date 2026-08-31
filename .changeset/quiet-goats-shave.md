---
'@platforma-open/milaboratories.sort-seq-analysis.model': patch
---

Results table shows only this block's scores. A second Sort-Seq Analysis block on the same
project exported columns the table's pool query could not tell apart from this one's, so both
runs' `gateRankMean` and `binScore` appeared side by side. The block's own columns now come
from its workflow output as the table's primary columns, and the whole `pl7.app/facsBin/`
namespace is excluded from the pool query.
