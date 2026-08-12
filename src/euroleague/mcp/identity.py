"""Server identity: name, version, and instructions.

This module is separate from the protocol layer to allow protocol.py to know
nothing about tools, domains, or any knowledge outside JSON-RPC framing itself.
"""

SERVER_INFO: dict[str, str] = {
    "name": "euroleague-analytics",
    "title": "EuroLeague Analytics Warehouse",
    "version": "0.1.0",
}

# Shown to the model once, at connection time.
SERVER_INSTRUCTIONS = (
    "A validated EuroLeague warehouse built from play-by-play events. Possessions are "
    "counted exactly from the event stream, never estimated from a box score formula. "
    "Counting statistics are the official published box score; possessions, lineups, "
    "on/off and every per-100 rate are this project's own reconstruction. Call "
    "el_describe_warehouse first to learn which seasons are loaded and which games are "
    "excluded. Every response reports what it excluded and whether minutes are raw or "
    "corrected: quote those alongside the numbers."
)

IDENTITY = {"serverInfo": SERVER_INFO, "instructions": SERVER_INSTRUCTIONS}
