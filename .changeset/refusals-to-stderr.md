---
'@platforma-open/milaboratories.sort-seq-analysis.software': patch
---

Write refusals to stderr as well as stdout, so the platform's error dialog shows them

The k8s runner fills a failed command's "Latest output" from the stderr file alone. A
refusal printed only to stdout therefore reached the user as a blank "exited with code 1",
with the actual reason sitting in the run's log panel.
