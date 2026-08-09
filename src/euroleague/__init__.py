"""A validated data warehouse for EuroLeague and EuroCup basketball.

Built from the public play-by-play API. The value is in the derived layer:
exact possession counts, four factors, and lineup-level on/off metrics
reconstructed from the event stream.

Read `CLAUDE.md` and `DECISIONS.md` before changing anything that touches the
data. The rules there were written from measurements, and several of them
protect against failures that produce plausible wrong answers rather than
errors.
"""

__version__ = "0.1.0"
