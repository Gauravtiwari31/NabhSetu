from __future__ import annotations

from uuid import UUID

from app.domain.models import ProvenanceLink


def observation_lineage(
    *,
    observation_id: UUID,
    raw_id: UUID | None,
    payload_id: UUID | None,
    attempt_id: UUID | None,
    source_id: UUID,
    hashes: dict[str, str | None],
) -> list[ProvenanceLink]:
    links = [
        ProvenanceLink(
            entity_type="normalised_observation",
            entity_id=observation_id,
            parent_type="raw_observation" if raw_id else "payload",
            parent_id=raw_id or payload_id,
            relation="normalised_from",
            content_hash=hashes.get("observation"),
        )
    ]
    if raw_id is not None:
        links.append(
            ProvenanceLink(
                entity_type="raw_observation",
                entity_id=raw_id,
                parent_type="payload" if payload_id else "attempt",
                parent_id=payload_id or attempt_id,
                relation="parsed_from",
                content_hash=hashes.get("raw"),
            )
        )
    if payload_id is not None:
        links.append(
            ProvenanceLink(
                entity_type="payload",
                entity_id=payload_id,
                parent_type="collection_attempt",
                parent_id=attempt_id,
                relation="captured_by",
                content_hash=hashes.get("payload"),
            )
        )
    if attempt_id is not None:
        links.append(
            ProvenanceLink(
                entity_type="collection_attempt",
                entity_id=attempt_id,
                parent_type="source",
                parent_id=source_id,
                relation="collected_from",
                content_hash=hashes.get("attempt"),
            )
        )
    return links
