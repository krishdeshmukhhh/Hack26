"""Shared, anonymous task map: a small HTTP server, its client and a demo seeder.

Only ``summary_to_wire`` / ``path_to_wire`` JSON crosses the network: no ids,
timestamps or window titles. See docs/map-sync.md.

Import ``curio.map_sync.client.HttpMapSync`` directly; this package imports
nothing so the server stays standard-library only.
"""
