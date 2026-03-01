"""Notification deduplication services for Phase 3.8.

Provides deduplication-aware notification processing:
- NotificationDeduplicator: Categorizes papers as new/retry/duplicate

Usage:
    from src.services.notification import NotificationDeduplicator

    deduplicator = NotificationDeduplicator(registry_service)
    result = deduplicator.categorize_papers(papers)
"""

from src.services.notification.deduplicator import NotificationDeduplicator

__all__ = ["NotificationDeduplicator"]
