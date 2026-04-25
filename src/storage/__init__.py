"""Storage backends for ARISP.

Each subpackage is a self-contained storage layer that may target
different backends (SQLite today, Neo4j/Postgres later). They sit
beneath the services layer so any service can consume them without
introducing a service↔service dependency.
"""
