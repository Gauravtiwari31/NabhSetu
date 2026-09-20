"""Source discovery classifies capabilities. It does not crawl aggressively."""

from app.acquisition.discovery.robots import RobotsSnapshot, fetch_robots

__all__ = ["RobotsSnapshot", "fetch_robots"]
