from __future__ import annotations

from apix_index.engine import compute
from apix_index.frequency import to_frequency
from apix_index.types import IndexResult
from app.config import DataMode, Settings
from app.database.models.publication import BasketVersion, WeightVersion
from app.database.repositories.observations import ObservationRepository
from app.database.repositories.publication import PublicationRepository
from app.domain.enums import IndexBasis, IndexFrequency, IndexVariant
from app.domain.hashing import sha256_canonical
from app.pipeline.method_config import load_basket, load_method_config, load_weight_set
from app.pipeline.quote_adapter import clean_observations


class IndexPublisher:
    def __init__(
        self,
        settings: Settings,
        observations: ObservationRepository,
        publications: PublicationRepository,
    ) -> None:
        self.settings = settings
        self.observations = observations
        self.publications = publications

    async def ensure_versions(self) -> tuple[BasketVersion, WeightVersion]:
        basket_payload = load_basket(self.settings)
        weights, weight_payload = load_weight_set(self.settings)
        basket = await self.publications.add_basket(
            BasketVersion(
                version=str(basket_payload.get("version", "basket-1.0.0")),
                name=str(basket_payload.get("name", "Nabhsetu basket")),
                method_version="1.0.0",
                routes_json=list(basket_payload.get("routes") or []),
                lead_windows_json=list(basket_payload.get("lead_windows") or []),
                carriers_json=list(basket_payload.get("carriers") or []),
                config_hash=sha256_canonical(basket_payload),
                notes=basket_payload.get("notes"),
            )
        )
        weight_row = await self.publications.add_weights(
            WeightVersion(
                version=str(weight_payload.get("version", weights.weights_version)),
                source=str(weight_payload.get("source", weights.source)),
                route_weights_json={key: format(value, "f") for key, value in weights.route_weights.items()},
                carrier_weights_json={
                    route: {carrier: format(value, "f") for carrier, value in table.items()}
                    for route, table in weights.carrier_weights.items()
                },
                notes=weight_payload.get("notes"),
            )
        )
        return basket, weight_row

    async def publish(
        self,
        *,
        bootstrap_draws: int | None = None,
        n_min: int | None = None,
        apply_dow_smoothing: bool | None = None,
    ) -> IndexResult:
        config = load_method_config(self.settings)
        overrides: dict = {}
        if bootstrap_draws is not None:
            overrides["bootstrap_draws"] = bootstrap_draws
        if n_min is not None:
            overrides["n_min"] = n_min
        if apply_dow_smoothing is not None:
            overrides["apply_dow_smoothing"] = apply_dow_smoothing
        if overrides:
            config = MethodConfigOverlay(config, **overrides)
        weights, _payload = load_weight_set(self.settings)
        basket, weight_row = await self.ensure_versions()
        simulated = self.settings.data_mode == DataMode.MOCK
        rows = await self.observations.list_publishable(simulated=simulated)
        quotes, checks = clean_observations(
            rows,
            tukey_k=config.tukey_k,
            hampel_z=config.hampel_z,
            freshness_hours=self.settings.index_freshness_hours,
        )
        run = await self.publications.create_run(
            method_version=config.method_version,
            basket_version_id=basket.id,
            weight_version_id=weight_row.id,
            basis=IndexBasis(config.basis),
            variant=IndexVariant(config.variant),
            omega_preset=config.omega_preset,
            input_hash=sha256_canonical(
                [{"id": str(row.id), "fare": format(row.total_fare, "f")} for row in rows]
            ),
            is_simulated=simulated,
        )
        for check in checks:
            await self.publications.add_quality(
                run.id,
                check["observation_id"],
                check["code"],
                check["disposition"],
                check["details"],
            )
        if not quotes:
            await self.publications.fail_run(run, "no publishable quotes after quality gates")
            raise ValueError("no publishable quotes after quality gates")
        result = compute(quotes, weights, config)
        await self.publications.complete_run(run, result, is_simulated=simulated)
        await self.publications.store_result(
            run,
            result,
            basket_version=basket.version,
            weights_version=weight_row.version,
            is_simulated=simulated,
        )
        weekly = to_frequency(result.headline, "weekly")
        monthly = to_frequency(result.headline, "monthly")
        await self.publications.store_frequency(
            run,
            weekly,
            IndexFrequency.WEEKLY,
            basket_version=basket.version,
            weights_version=weight_row.version,
            is_simulated=simulated,
        )
        await self.publications.store_frequency(
            run,
            monthly,
            IndexFrequency.MONTHLY,
            basket_version=basket.version,
            weights_version=weight_row.version,
            is_simulated=simulated,
        )
        return result


def MethodConfigOverlay(config, **overrides):
    from dataclasses import replace

    return replace(config, **overrides)
