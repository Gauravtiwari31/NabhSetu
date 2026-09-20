# Index methodology

The pure engine lives in `backend/apix_index/` and remains free of I/O.
`method_version=1.0.0` is loaded from `backend/config/method.yaml`.

## Formulae

- **Jevons** elementary index: geometric mean of matched price relatives, base = 100.
- **Availability adjustment**: \(I_{adj} = I_{matched}^{A} \cdot I_{LAF}^{1-A}\). At \(A=1\) this equals the matched index.
- **Young aggregation**: weighted arithmetic mean of surviving cells, then routes, then lead-time windows.
- **Lead-time weights** \(\omega_\tau\) are declared presets (uniform, near_term, leisure) over T+1/7/15/30/45.
- **Frequencies**: daily levels first; weekly and monthly by geometric aggregation.
- **Late entrants** are not chain-linked. Unmatched cells are suppressed and their weight is redistributed.

APIx-T is the headline traveller-paid index. Dual bases: book-date and travel-date.

Every published point is stamped with method, basket, and weights versions plus coverage and confidence metadata.

## Quality gates

Quotes reach publication only as `ACCEPTED` or `WINSORISED`. Sold-out, stale, and excluded observations are quarantined. Cell-level Tukey/Hampel checks winsorise outliers rather than rewriting the immutable ledger.

## Official validation

DGCA and CPI loaders accept downloaded public files, store URL/file/checksum provenance, and never fabricate official series. The back-test returns `unavailable` or `not_reportable` when a compatible comparator or sufficient monthly overlap is missing.
