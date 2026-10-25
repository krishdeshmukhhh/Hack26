"""Replayable accuracy + latency benchmark for the Curio vision model.

``capture`` records a screen scenario once; ``run`` replays it against the
configured model; ``scoring`` and ``request`` are pure and unit-tested.
"""
