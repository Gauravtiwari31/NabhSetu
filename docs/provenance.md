# Provenance

Every stored observation carries:

- payload SHA-256
- raw record hash
- parser name and version
- collector modality
- source id
- optional egress id / session id (never credentials)

`provenance_records` form a hash chain:

`chain_hash_n = SHA256(chain_hash_{n-1} || canonical(record_n))`

Lineage for this milestone:

```
collection job → normalised observation → raw observation → payload → attempt → source
```

Index-run lineage will attach when `apix_index` publishes values.
