"""Sizing for vol_event_persistence.

Single-leg perpetual order intents. Unlike A1 (two-leg perp+spot funding
capture), this engine takes discrete directional perp positions on vol
events and closes them at a fixed horizon (spec §7). There is no spot
hedge leg and no delta-to-target rebalancing.
"""
