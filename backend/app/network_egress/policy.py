"""Source network-policy helpers."""

from app.config import EgressMode as SettingsEgressMode
from app.domain.enums import EgressMode, RotationStrategy
from app.domain.models import SourceNetworkPolicy, SourceProfile

FORBIDDEN_STRATEGIES = {
    "rotate-on-http-403",
    "rotate-on-captcha-challenge",
    "rotate-on-source-block",
}


def effective_mode(source: SourceProfile, global_mode: SettingsEgressMode) -> EgressMode:
    if global_mode == SettingsEgressMode.DIRECT:
        return EgressMode.DIRECT
    if not source.network_policy.enabled:
        return EgressMode.DIRECT
    return source.network_policy.egress_mode


def assert_rotation_allowed(policy: SourceNetworkPolicy) -> None:
    if policy.rotation_strategy.value.upper() in FORBIDDEN_STRATEGIES:
        raise ValueError("rotation strategy is not permitted")
    if policy.rotation_strategy not in RotationStrategy:
        raise ValueError("unknown rotation strategy")
