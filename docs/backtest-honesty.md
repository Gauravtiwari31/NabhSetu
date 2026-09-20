# Back-test honesty

The 30-day (or monthly) comparison against DGCA fare/yield or CPI air-fare data
refuses to invent a story.

| Status | Meaning |
|--------|---------|
| `unavailable` | No compatible official file rows were imported. |
| `not_reportable` | Monthly APIx is missing, or overlap is below 3 months. Correlation is not published. |
| `reportable` | Pearson correlation and MAPE are computed on overlapping months of real imported values. |

The API and dashboard surface the status and notes. Do not hard-code a
correlation in slides. After a real 30-day run, record the manifest (input
hashes, method version, weight file checksum, comparator URL) instead of a
claimed figure.
