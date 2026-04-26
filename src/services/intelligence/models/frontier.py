"""Research-frontier enums (Milestone 9.4)."""

from enum import Enum


class TrendStatus(str, Enum):
    """Status of a research trend (Milestone 9.4)."""

    EMERGING = "emerging"  # Low volume, high acceleration
    GROWING = "growing"  # High volume, positive acceleration
    PEAKED = "peaked"  # High volume, zero/negative acceleration
    DECLINING = "declining"  # Decreasing volume
    NICHE = "niche"  # Consistently low volume


class GapType(str, Enum):
    """Types of research gaps (Milestone 9.4)."""

    INTERSECTION = "intersection"  # Topic A + Topic B underexplored
    APPLICATION = "application"  # Method not applied to domain
    SCALE = "scale"  # Not tested at different scales
    MODALITY = "modality"  # Not explored in other modalities
    REPLICATION = "replication"  # Results not independently verified
