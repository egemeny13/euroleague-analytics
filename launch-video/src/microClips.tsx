import React from 'react';
import {
  AbsoluteFill,
  Audio,
  Easing,
  Sequence,
  interpolate,
  staticFile,
  useCurrentFrame,
} from 'remotion';

const palette = {
  paper: '#F4F0E8',
  paperBright: '#FBF8F1',
  ink: '#181916',
  inkSoft: '#5D5E58',
  inkFaint: '#9D9B91',
  rule: '#D7D0C4',
  orange: '#F25C24',
  orangeSoft: '#F7C7B3',
};

const sans = 'Instrument Sans, Arial, sans-serif';
const mono = 'IBM Plex Mono, Consolas, monospace';

const ease = Easing.bezier(0.22, 1, 0.36, 1);
const easeInOut = Easing.bezier(0.65, 0, 0.35, 1);

const between = (
  frame: number,
  input: number[],
  output: number[],
  easing = ease
) =>
  interpolate(frame, input, output, {
    easing,
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

const windowOpacity = (frame: number, start: number, end: number, fade = 12) =>
  between(frame, [start, start + fade, end - fade, end], [0, 1, 1, 0]);

const FontFaces: React.FC = () => (
  <style>{`
    @font-face {
      font-family: 'Instrument Sans';
      src: url('${staticFile('fonts/InstrumentSans-Regular.woff2')}') format('woff2');
      font-weight: 400;
      font-style: normal;
    }
    @font-face {
      font-family: 'Instrument Sans';
      src: url('${staticFile('fonts/InstrumentSans-SemiBold.woff2')}') format('woff2');
      font-weight: 600;
      font-style: normal;
    }
    @font-face {
      font-family: 'Instrument Sans';
      src: url('${staticFile('fonts/InstrumentSans-Bold.woff2')}') format('woff2');
      font-weight: 700;
      font-style: normal;
    }
    @font-face {
      font-family: 'IBM Plex Mono';
      src: url('${staticFile('fonts/IBMPlexMono-Regular.ttf')}') format('truetype');
      font-weight: 400;
      font-style: normal;
    }
    @font-face {
      font-family: 'IBM Plex Mono';
      src: url('${staticFile('fonts/IBMPlexMono-Medium.ttf')}') format('truetype');
      font-weight: 500;
      font-style: normal;
    }
  `}</style>
);

const HeaderBadge: React.FC<{ label: string; frame: number }> = ({ label, frame }) => {
  const opacity = between(frame, [0, 15, 270, 300], [0, 1, 1, 0]);
  return (
    <div
      style={{
        position: 'absolute',
        left: 116,
        right: 116,
        top: 64,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        opacity,
        fontFamily: mono,
        fontSize: 14,
        letterSpacing: '0.08em',
        textTransform: 'uppercase',
        color: palette.inkSoft,
      }}
    >
      <span>EuroLeague Analytics</span>
      <span style={{ color: palette.orange }}>{label}</span>
      <span>egemenyucelen.me</span>
    </div>
  );
};

/**
 * Clip A: TJ Shorts On/Off Split (10 seconds / 300 frames @ 30fps)
 */
export const ClipTJShorts: React.FC = () => {
  const frame = useCurrentFrame();
  const question = 'How did Paris perform with TJ Shorts on vs. off the floor in E2024?';
  const count = Math.floor(between(frame, [15, 85], [0, question.length], Easing.linear));
  const typed = question.slice(0, count);
  const submitted = frame >= 95;

  const queryOpacity = windowOpacity(frame, 0, 140, 10);
  const toolOpacity = windowOpacity(frame, 95, 155, 8);
  const answerOpacity = windowOpacity(frame, 145, 285, 10);
  const answerEnter = between(frame, [145, 175], [40, 0]);

  return (
    <AbsoluteFill style={{ background: palette.paper, overflow: 'hidden' }}>
      <FontFaces />
      <Audio src={staticFile('audio/codex-music.wav')} volume={between(frame, [0, 20, 270, 300], [0, 0.65, 0.65, 0])} />
      <Sequence from={15} durationInFrames={75}>
        <Audio src={staticFile('audio/codex-typing.wav')} volume={0.55} />
      </Sequence>
      <Sequence from={95} durationInFrames={16}>
        <Audio src={staticFile('audio/codex-enter.wav')} volume={0.75} />
      </Sequence>
      <Sequence from={145} durationInFrames={24}>
        <Audio src={staticFile('audio/codex-swish.wav')} volume={0.45} />
      </Sequence>

      <HeaderBadge label="Player Impact Split" frame={frame} />

      {/* Query Bar */}
      <div
        style={{
          position: 'absolute',
          left: 140,
          right: 140,
          top: 180,
          opacity: queryOpacity,
          borderBottom: `1px solid ${submitted ? palette.rule : palette.orange}`,
          paddingBottom: 16,
        }}
      >
        <div style={{ fontFamily: mono, fontSize: 13, color: palette.orange, textTransform: 'uppercase', marginBottom: 8 }}>
          Ask EuroLeague Analytics
        </div>
        <div style={{ fontFamily: sans, fontSize: 32, fontWeight: 500, color: palette.ink }}>
          {typed}
          {!submitted && Math.floor(frame / 8) % 2 === 0 ? <span style={{ color: palette.orange }}>|</span> : null}
        </div>
      </div>

      {/* Tool Call Status */}
      <div
        style={{
          position: 'absolute',
          left: 140,
          right: 140,
          top: 290,
          opacity: toolOpacity,
          fontFamily: mono,
          fontSize: 15,
          display: 'flex',
          gap: 16,
          color: palette.inkSoft,
        }}
      >
        <span style={{ color: palette.orange }}>mcp</span>
        <span style={{ color: palette.ink, fontWeight: 500 }}>el_get_player_on_off</span>
        <span>PRS · TJ Shorts · E2024</span>
      </div>

      {/* Answer Hero Card */}
      <div
        style={{
          position: 'absolute',
          left: 140,
          right: 140,
          top: 360,
          opacity: answerOpacity,
          transform: `translateY(${answerEnter}px)`,
          display: 'grid',
          gridTemplateColumns: '1fr 1px 1fr 1px 1.2fr',
          alignItems: 'center',
          gap: 40,
          background: palette.paperBright,
          padding: '48px 56px',
          border: `1px solid ${palette.rule}`,
        }}
      >
        <div>
          <div style={{ fontFamily: mono, fontSize: 13, color: palette.orange, textTransform: 'uppercase', marginBottom: 12 }}>
            Shorts On Court
          </div>
          <div style={{ fontFamily: sans, fontSize: 88, fontWeight: 600, color: palette.ink, lineHeight: 0.9 }}>
            +5.09
          </div>
          <div style={{ fontFamily: mono, fontSize: 13, color: palette.inkFaint, marginTop: 16 }}>
            1,667 possessions · 116.14 ORtg
          </div>
        </div>

        <div style={{ width: 1, height: 160, background: palette.rule }} />

        <div>
          <div style={{ fontFamily: mono, fontSize: 13, color: palette.inkSoft, textTransform: 'uppercase', marginBottom: 12 }}>
            Shorts Off Court
          </div>
          <div style={{ fontFamily: sans, fontSize: 88, fontWeight: 600, color: palette.ink, lineHeight: 0.9 }}>
            −11.45
          </div>
          <div style={{ fontFamily: mono, fontSize: 13, color: palette.inkFaint, marginTop: 16 }}>
            821 possessions · 128.50 DRtg
          </div>
        </div>

        <div style={{ width: 1, height: 160, background: palette.rule }} />

        <div style={{ textAlign: 'center' }}>
          <div style={{ fontFamily: mono, fontSize: 13, color: palette.orange, textTransform: 'uppercase', marginBottom: 8 }}>
            Net Rating Swing
          </div>
          <div style={{ fontFamily: sans, fontSize: 98, fontWeight: 700, color: palette.ink, lineHeight: 0.9 }}>
            +16<span style={{ color: palette.orange }}>.54</span>
          </div>
          <div style={{ fontFamily: mono, fontSize: 13, color: palette.inkFaint, marginTop: 16 }}>
            34 games · 2,488 total poss
          </div>
        </div>
      </div>
    </AbsoluteFill>
  );
};

/**
 * Clip B: Dual-Path Trust & Invariants (8 seconds / 240 frames @ 30fps)
 */
export const ClipVerification: React.FC = () => {
  const frame = useCurrentFrame();
  const opacity = windowOpacity(frame, 0, 240, 10);
  const cardEnter = between(frame, [10, 40], [30, 0]);

  return (
    <AbsoluteFill style={{ background: palette.paper, overflow: 'hidden' }}>
      <FontFaces />
      <Audio src={staticFile('audio/codex-music.wav')} volume={between(frame, [0, 15, 215, 240], [0, 0.65, 0.65, 0])} />
      <Sequence from={35} durationInFrames={24}>
        <Audio src={staticFile('audio/codex-air.wav')} volume={0.45} />
      </Sequence>

      <HeaderBadge label="Data Integrity & Invariants" frame={frame} />

      <div
        style={{
          position: 'absolute',
          inset: 0,
          opacity,
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'center',
          alignItems: 'center',
          transform: `translateY(${cardEnter}px)`,
        }}
      >
        <div style={{ fontFamily: mono, fontSize: 15, color: palette.orange, letterSpacing: '0.12em', textTransform: 'uppercase', marginBottom: 20 }}>
          Re-earned from the event stream
        </div>
        <div style={{ fontFamily: sans, fontSize: 72, fontWeight: 600, color: palette.ink, letterSpacing: '-0.04em', textAlign: 'center', marginBottom: 64 }}>
          Proven against official box scores.
        </div>

        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(3, 360px)',
            gap: 32,
          }}
        >
          <div style={{ background: palette.paperBright, padding: '36px 32px', border: `1px solid ${palette.rule}`, textAlign: 'center' }}>
            <div style={{ fontFamily: sans, fontSize: 64, fontWeight: 700, color: palette.ink, lineHeight: 1 }}>
              107,311
            </div>
            <div style={{ fontFamily: sans, fontSize: 18, color: palette.inkSoft, marginTop: 10 }}>
              Possessions Counted
            </div>
            <div style={{ fontFamily: mono, fontSize: 12, color: palette.inkFaint, marginTop: 8 }}>
              5 verified ending criteria
            </div>
          </div>

          <div style={{ background: palette.paperBright, padding: '36px 32px', border: `1px solid ${palette.rule}`, textAlign: 'center' }}>
            <div style={{ fontFamily: sans, fontSize: 64, fontWeight: 700, color: palette.ink, lineHeight: 1 }}>
              732
            </div>
            <div style={{ fontFamily: sans, fontSize: 18, color: palette.inkSoft, marginTop: 10 }}>
              Loaded Public Games
            </div>
            <div style={{ fontFamily: mono, fontSize: 12, color: palette.inkFaint, marginTop: 8 }}>
              330 E2024 · 402 E2025
            </div>
          </div>

          <div style={{ background: palette.paperBright, padding: '36px 32px', border: `1px solid ${palette.rule}`, textAlign: 'center' }}>
            <div style={{ fontFamily: sans, fontSize: 64, fontWeight: 700, color: palette.ink, lineHeight: 1 }}>
              100<span style={{ color: palette.orange }}>%</span>
            </div>
            <div style={{ fontFamily: sans, fontSize: 18, color: palette.inkSoft, marginTop: 10 }}>
              Score Reconciliation
            </div>
            <div style={{ fontFamily: mono, fontSize: 12, color: palette.inkFaint, marginTop: 8 }}>
              0 point discrepancies
            </div>
          </div>
        </div>

        <div style={{ fontFamily: mono, fontSize: 14, color: palette.inkSoft, marginTop: 48 }}>
          Dual-Path Evaluations: 10 / 10 passed via ground-truth SQL and live MCP tool calls
        </div>
      </div>
    </AbsoluteFill>
  );
};
