# EuroLeague Analytics — Codex launch film

## Deliverable

- Composition: `EuroLeagueLaunchCodex`
- Master: `output/euroleague-launch-codex.mp4`
- Format: H.264 video + AAC stereo audio in MP4
- Raster / cadence: 1920×1080, 30 fps, 900 frames
- Exact container duration: 30.000 seconds
- Rebuild: `npm run build:codex`

The Codex composition and output are independent of the existing
`EuroLeagueLaunch` attempt. The finalization step stream-copies the rendered
H.264/AAC streams into an exact 30.000-second MP4 container; the video remains
900 frames and the audio ends at 29.994667 seconds.

## Repository-backed story and facts

The film uses evaluation 02 from `../evaluation.xml`, scoped to non-quarantined
E2024 games for Paris Basketball and TJ Shorts:

- On court: +5.09 net rating, based on 1,667 offensive possessions across 34
  included games.
- Off court: -11.45 net rating, based on 821 offensive possessions across 34
  included games.
- On/off swing: +16.54, calculated as `+5.09 - (-11.45)`.
- The shown tool name, `el_get_player_on_off`, is the current registered MCP
  tool in `../src/euroleague/mcp/tools.py`.

The proof sequence uses the verified integrity table in `../README.md`:

- 107,311 reconstructed possessions.
- 732 loaded public games: 330 E2024 and 402 E2025.
- 100.0% final-score reconciliation: 0 point discrepancies across all 732
  games.
- The small evaluation annotation is supported by the repository's 10/10
  dual-path evaluation result, verified through ground-truth SQL and live MCP.

## Creative system

The story is one continuous editorial field rather than a stack of UI cards:
the substitution premise becomes a typed question; that same line moves into
conversation history; the camera tracks the live MCP state; the answer divides
the court into on/off halves; the difference becomes the +16.54 hero; that
number hands focus to the verification sequence; a hard cut creates the quiet
identity close.

The visual system uses warm paper, charcoal, and one restrained orange. Court
geometry is structural and nearly invisible rather than decorative. Motion is
reserved for attention changes: approach the input, reframe the tool state,
settle on the answer, pull back through proof, then stop.

## Reference principles

- [Raycast AI launch film](https://www.youtube.com/watch?v=nKYeAhsWF70): keep
  the current product action dominant, let context recede, and cut when user
  intent changes rather than on arbitrary time intervals.
- [Vercel AI](https://vercel.com/ai): use typography, whitespace, and restrained
  contrast to communicate technical confidence without ornamental UI.
- [EuroLeague “Born Not Built” campaign](https://mediacentre.euroleague.net/en/app/2/communication/communication/preview/23529): borrow authentic, bold,
  emotional rhythm and white/orange energy without copying league branding or
  using broadcast footage.

These were treated as direction principles, not layout or animation templates.

## Typography and licenses

- Instrument Sans — primary editorial sans. SIL Open Font License 1.1. Source:
  [Instrument Sans repository](https://github.com/Instrument/instrument-sans).
  Local license: `public/fonts/InstrumentSans-OFL.txt`.
- IBM Plex Mono — process labels and technical annotations. SIL Open Font
  License 1.1. Source: [IBM Plex repository](https://github.com/IBM/plex).
  Local license: `public/fonts/IBMPlexMono-OFL.txt`.

No third-party imagery, video, icons, music, or sound effects are used.

## Music and sound

All audio is original and generated deterministically by
`scripts/generate-codex-audio.js` at 48 kHz stereo:

- `codex-music.wav`: a restrained 100 BPM warm electronic bed with sub pulse,
  sparse kick, wood transient, and filtered noise.
- `codex-typing.wav`: irregular mechanical key ticks matched to the typing beat.
- `codex-enter.wav`: low key impact.
- `codex-tool.wav`: short confirmed-state tick.
- `codex-swish.wav`: synthesized, highly restrained net-like punctuation on the
  +16.54 reveal.
- `codex-air.wav`: soft transition air used at the proof handoff and close.

Because these assets are synthesized locally from source code, there are no
external audio licenses or attribution requirements.

## Refinement record

The first full render review removed a crowded answer-to-hero overlap, shortened
the processing state's tail, moved the attention trace off the off-court value,
extended typing audio to the full question, and increased small proof copy.

The second full render review found a hero/proof collision and an ambiguous
ending dissolve. The final pass ends the +16.54 hero before the possession
proof lands, strengthens the 107,311 hierarchy in the final three-metric field,
and replaces the dissolve with a two-frame editorial cut at 27 seconds.

## Deliberate rejections from the prior attempt

- Separate title, input, stat-card, proof-card, and logo slides.
- Rounded SaaS cards as the dominant composition device.
- A system-font stack and generic centered push-ins.
- The prior `el_get_on_off_splits` label, which is not the current registered
  tool name.
- Repeated scene resets and decorative effects used only to fill space.

## Remaining limitation

The proof field must communicate three integrity facts in roughly three
seconds, so its smallest annotations reward a large-screen viewing and are not
intended to be primary mobile copy. The main question, answer, and proof numbers
remain readable; the annotations are supporting texture.
