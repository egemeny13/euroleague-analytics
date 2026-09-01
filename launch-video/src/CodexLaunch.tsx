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

const windowOpacity = (frame: number, start: number, end: number, fade = 14) =>
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

const CourtField: React.FC<{ frame: number }> = ({ frame }) => {
  const opacity = between(frame, [0, 80, 840, 900], [0.55, 0.28, 0.2, 0]);
  const drift = between(frame, [0, 900], [0, -42], Easing.linear);
  return (
    <AbsoluteFill style={{ opacity, transform: `translateX(${drift}px)` }}>
      <div
        style={{
          position: 'absolute',
          left: 88,
          right: 88,
          top: 74,
          bottom: 74,
          border: `1px solid ${palette.rule}`,
        }}
      />
      <div
        style={{
          position: 'absolute',
          left: 960,
          top: 74,
          bottom: 74,
          width: 1,
          background: palette.rule,
        }}
      />
      <div
        style={{
          position: 'absolute',
          left: 824,
          top: 405,
          width: 272,
          height: 272,
          border: `1px solid ${palette.rule}`,
          borderRadius: '50%',
        }}
      />
      <div
        style={{
          position: 'absolute',
          left: 88,
          top: 286,
          width: 238,
          height: 508,
          border: `1px solid ${palette.rule}`,
          borderLeft: 0,
        }}
      />
      <div
        style={{
          position: 'absolute',
          right: 88,
          top: 286,
          width: 238,
          height: 508,
          border: `1px solid ${palette.rule}`,
          borderRight: 0,
        }}
      />
    </AbsoluteFill>
  );
};

const EditorialHeader: React.FC<{ frame: number }> = ({ frame }) => {
  const opacity = between(frame, [0, 20, 825, 860], [0, 1, 1, 0]);
  return (
    <div
      style={{
        position: 'absolute',
        left: 116,
        right: 116,
        top: 76,
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
      <span style={{ color: palette.orange }}>Possession-level answers</span>
      <span>E2024 · evaluation 02</span>
    </div>
  );
};

const AttentionTrace: React.FC<{ frame: number }> = ({ frame }) => {
  const x = between(
    frame,
    [0, 78, 118, 300, 350, 420, 520, 620, 705, 805, 900],
    [1110, 1110, 178, 178, 1630, 960, 930, 930, 1460, 1740, 1740],
    easeInOut
  );
  const y = between(
    frame,
    [0, 78, 118, 300, 350, 420, 520, 620, 705, 805, 900],
    [675, 675, 735, 735, 220, 486, 486, 486, 692, 790, 790],
    easeInOut
  );
  const size = between(frame, [0, 65, 100, 300, 420, 520, 900], [0, 26, 14, 14, 18, 13, 13]);
  const opacity = between(frame, [0, 20, 840, 885], [0, 1, 1, 0]);
  return (
    <div
      style={{
        position: 'absolute',
        left: x - size / 2,
        top: y - size / 2,
        width: size,
        height: size,
        borderRadius: '50%',
        background: palette.orange,
        opacity,
      }}
    />
  );
};

const Hook: React.FC<{ frame: number }> = ({ frame }) => {
  const opacity = windowOpacity(frame, 0, 132, 18);
  const lift = between(frame, [0, 92, 132], [0, 0, -175]);
  const scale = between(frame, [0, 92, 132], [1, 1, 0.82]);
  const lineOne = between(frame, [12, 42], [34, 0]);
  const lineTwo = between(frame, [40, 76], [44, 0]);
  return (
    <div
      style={{
        position: 'absolute',
        left: 158,
        top: 270,
        width: 1240,
        opacity,
        transform: `translateY(${lift}px) scale(${scale})`,
        transformOrigin: 'left center',
      }}
    >
      <div
        style={{
          fontFamily: mono,
          fontSize: 16,
          letterSpacing: '0.12em',
          textTransform: 'uppercase',
          color: palette.orange,
          marginBottom: 28,
          opacity: between(frame, [4, 22], [0, 1]),
        }}
      >
        One substitution. One question.
      </div>
      <div
        style={{
          fontFamily: sans,
          fontSize: 112,
          lineHeight: 0.96,
          letterSpacing: '-0.065em',
          fontWeight: 600,
          color: palette.ink,
        }}
      >
        <div
          style={{
            opacity: between(frame, [10, 36], [0, 1]),
            transform: `translateY(${lineOne}px)`,
          }}
        >
          One player leaves.
        </div>
        <div
          style={{
            marginTop: 18,
            opacity: between(frame, [38, 72], [0, 1]),
            transform: `translateY(${lineTwo}px)`,
          }}
        >
          <span style={{ color: palette.inkSoft }}>What </span>
          <span style={{ color: palette.orange }}>changes?</span>
        </div>
      </div>
    </div>
  );
};

const Query: React.FC<{ frame: number }> = ({ frame }) => {
  const question = 'How did Paris perform with TJ Shorts on vs. off the floor in E2024?';
  const count = Math.floor(between(frame, [132, 288], [0, question.length], Easing.linear));
  const typed = question.slice(0, count);
  const submitted = frame >= 304;
  const opacity = windowOpacity(frame, 92, 446, 18);
  const y = between(frame, [92, 124, 304, 350], [780, 735, 735, 220]);
  const width = between(frame, [92, 124, 304, 350], [0, 1580, 1580, 1260]);
  const fontSize = between(frame, [304, 350], [42, 27]);
  const cursor = !submitted && Math.floor(frame / 8) % 2 === 0;
  const promptLabelOpacity = between(frame, [110, 132, 304, 332], [0, 1, 1, 0]);
  return (
    <div
      style={{
        position: 'absolute',
        left: 170,
        top: y,
        width,
        height: 1,
        background: submitted ? palette.rule : palette.orange,
        opacity,
      }}
    >
      <div
        style={{
          position: 'absolute',
          left: 0,
          bottom: 24,
          fontFamily: mono,
          fontSize: 13,
          color: palette.orange,
          letterSpacing: '0.11em',
          textTransform: 'uppercase',
          opacity: promptLabelOpacity,
        }}
      >
        Ask EuroLeague Analytics
      </div>
      <div
        style={{
          position: 'absolute',
          left: 0,
          bottom: submitted ? 32 : 28,
          width: '100%',
          fontFamily: sans,
          fontSize,
          fontWeight: 500,
          color: palette.ink,
          letterSpacing: '-0.032em',
          whiteSpace: 'nowrap',
        }}
      >
        {typed}
        {cursor ? <span style={{ color: palette.orange }}>|</span> : null}
      </div>
      <div
        style={{
          position: 'absolute',
          right: 0,
          top: 18,
          fontFamily: mono,
          fontSize: 13,
          color: palette.inkSoft,
          opacity: between(frame, [270, 292, 304, 320], [0, 1, 1, 0]),
        }}
      >
        Press Enter ↵
      </div>
    </div>
  );
};

const Process: React.FC<{ frame: number }> = ({ frame }) => {
  const opacity = windowOpacity(frame, 320, 442, 12);
  const progress = between(frame, [332, 400], [0, 1], easeInOut);
  const completed = frame >= 405;
  return (
    <div
      style={{
        position: 'absolute',
        left: 170,
        top: 310,
        width: 1260,
        opacity,
        fontFamily: mono,
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 18,
          color: palette.inkSoft,
          fontSize: 15,
        }}
      >
        <span style={{ color: palette.orange }}>mcp</span>
        <span style={{ color: palette.ink, fontWeight: 500 }}>el_get_player_on_off</span>
        <span>season E2024</span>
        <span>player SHORTS, TJ</span>
        <span>team PRS</span>
        <span style={{ marginLeft: 'auto', color: completed ? palette.orange : palette.inkSoft }}>
          {completed ? 'verified response' : 'reading verified views'}
        </span>
      </div>
      <div style={{ height: 1, background: palette.rule, marginTop: 18, position: 'relative' }}>
        <div
          style={{
            position: 'absolute',
            left: 0,
            top: 0,
            width: `${progress * 100}%`,
            height: 1,
            background: palette.orange,
          }}
        />
      </div>
      <div
        style={{
          marginTop: 15,
          color: palette.inkFaint,
          fontSize: 13,
          letterSpacing: '0.02em',
        }}
      >
        {completed
          ? '34 included games · non-quarantined scope · corrected minutes disclosed'
          : 'resolving player identity · applying non-quarantined season scope'}
      </div>
    </div>
  );
};

const Answer: React.FC<{ frame: number }> = ({ frame }) => {
  const opacity = windowOpacity(frame, 410, 648, 15);
  const enter = between(frame, [410, 448], [52, 0]);
  const compress = between(frame, [540, 616], [1, 0.64], easeInOut);
  const shift = between(frame, [540, 616], [0, -420], easeInOut);
  const splitOpacity = between(frame, [486, 520, 542], [1, 1, 0]);
  const heroOpacity = between(frame, [505, 536, 578, 604], [0, 1, 1, 0]);
  return (
    <div
      style={{
        position: 'absolute',
        inset: 0,
        opacity,
        transform: `translateY(${enter}px)`,
      }}
    >
      <div
        style={{
          position: 'absolute',
          left: 170,
          right: 170,
          top: 440,
          display: 'grid',
          gridTemplateColumns: '1fr 1px 1fr',
          columnGap: 64,
          opacity: splitOpacity,
          transform: `translateX(${shift}px) scale(${compress})`,
          transformOrigin: 'center center',
        }}
      >
        <div>
          <div
            style={{
              fontFamily: mono,
              fontSize: 14,
              letterSpacing: '0.12em',
              textTransform: 'uppercase',
              color: palette.orange,
              marginBottom: 20,
            }}
          >
            TJ Shorts on court
          </div>
          <div
            style={{
              fontFamily: sans,
              fontSize: 154,
              fontWeight: 600,
              lineHeight: 0.8,
              letterSpacing: '-0.075em',
              color: palette.ink,
            }}
          >
            +5.09
          </div>
          <div style={{ fontFamily: sans, fontSize: 24, color: palette.inkSoft, marginTop: 32 }}>
            net rating
          </div>
          <div style={{ fontFamily: mono, fontSize: 14, color: palette.inkFaint, marginTop: 14 }}>
            1,667 offensive possessions · 34 games
          </div>
        </div>
        <div style={{ width: 1, height: 240, background: palette.rule }} />
        <div>
          <div
            style={{
              fontFamily: mono,
              fontSize: 14,
              letterSpacing: '0.12em',
              textTransform: 'uppercase',
              color: palette.inkSoft,
              marginBottom: 20,
            }}
          >
            TJ Shorts off court
          </div>
          <div
            aria-label="-11.45 net rating"
            style={{
              fontFamily: sans,
              fontSize: 154,
              fontWeight: 600,
              lineHeight: 0.8,
              letterSpacing: '-0.075em',
              color: palette.ink,
            }}
          >
            −11.45
          </div>
          <div style={{ fontFamily: sans, fontSize: 24, color: palette.inkSoft, marginTop: 32 }}>
            net rating
          </div>
          <div style={{ fontFamily: mono, fontSize: 14, color: palette.inkFaint, marginTop: 14 }}>
            821 offensive possessions · 34 games
          </div>
        </div>
      </div>

      <div
        style={{
          position: 'absolute',
          left: 0,
          right: 0,
          top: 402,
          textAlign: 'center',
          opacity: heroOpacity,
          transform: `scale(${between(frame, [495, 540, 610], [0.88, 1, 1.06])})`,
        }}
      >
        <div style={{ fontFamily: mono, fontSize: 14, color: palette.orange, letterSpacing: '0.14em' }}>
          ON − OFF
        </div>
        <div
          aria-label="+16.54 net rating swing"
          style={{
            fontFamily: sans,
            fontSize: 220,
            fontWeight: 600,
            letterSpacing: '-0.085em',
            lineHeight: 0.92,
            color: palette.ink,
            marginTop: 10,
          }}
        >
          +16<span style={{ color: palette.orange }}>.54</span>
        </div>
        <div style={{ fontFamily: sans, fontSize: 30, color: palette.inkSoft, marginTop: 20 }}>
          net rating swing with TJ Shorts on the floor
        </div>
        <div style={{ fontFamily: mono, fontSize: 14, color: palette.inkFaint, marginTop: 18 }}>
          Dual-path evaluation: ground-truth SQL + live MCP · passed
        </div>
      </div>
    </div>
  );
};

const Proof: React.FC<{ frame: number }> = ({ frame }) => {
  const opacity = windowOpacity(frame, 604, 816, 14);
  const firstScale = between(frame, [608, 658, 716], [0.78, 1, 0.64], easeInOut);
  const firstX = between(frame, [658, 716], [0, -470], easeInOut);
  const firstY = between(frame, [658, 716], [0, -76], easeInOut);
  const secondOpacity = between(frame, [684, 716], [0, 1]);
  const groupScale = between(frame, [716, 774], [1, 0.86], easeInOut);
  const groupX = between(frame, [716, 774], [0, -340], easeInOut);
  const thirdOpacity = between(frame, [746, 782], [0, 1]);
  return (
    <div style={{ position: 'absolute', inset: 0, opacity }}>
      <div
        style={{
          position: 'absolute',
          left: 0,
          right: 0,
          top: 300,
          textAlign: 'center',
          transform: `translate(${firstX}px, ${firstY}px) scale(${firstScale})`,
        }}
      >
        <div style={{ fontFamily: sans, fontWeight: 600, fontSize: 202, letterSpacing: '-0.08em', color: palette.ink }}>
          107,311
        </div>
        <div style={{ fontFamily: sans, fontSize: 30, color: palette.inkSoft, marginTop: -10 }}>
          possessions reconstructed from play-by-play
        </div>
        <div style={{ fontFamily: mono, fontSize: 14, color: palette.inkFaint, marginTop: 18 }}>
          five verified possession-ending criteria · no box-score estimate
        </div>
      </div>

      <div
        style={{
          position: 'absolute',
          left: 0,
          right: 0,
          top: 342,
          display: 'flex',
          justifyContent: 'center',
          alignItems: 'flex-start',
          gap: 120,
          opacity: secondOpacity,
          transform: `translateX(${groupX}px) scale(${groupScale})`,
        }}
      >
        <div style={{ width: 470 }} />
        <div style={{ width: 420 }}>
          <div style={{ fontFamily: sans, fontWeight: 600, fontSize: 170, letterSpacing: '-0.075em', color: palette.ink }}>
            732
          </div>
          <div style={{ fontFamily: sans, fontSize: 27, color: palette.inkSoft, marginTop: -2 }}>
            public games loaded
          </div>
          <div style={{ fontFamily: mono, fontSize: 14, color: palette.inkFaint, marginTop: 18 }}>
            330 E2024 · 402 E2025
          </div>
        </div>
      </div>

      <div
        style={{
          position: 'absolute',
          left: 1190,
          top: 338,
          width: 570,
          opacity: thirdOpacity,
        }}
      >
        <div aria-label="100% final-score reconciliation" style={{ fontFamily: sans, fontWeight: 600, fontSize: 170, letterSpacing: '-0.075em', color: palette.ink }}>
          100<span style={{ color: palette.orange }}>%</span>
        </div>
        <div style={{ fontFamily: sans, fontSize: 27, color: palette.inkSoft, marginTop: -2 }}>
          final-score reconciliation
        </div>
        <div style={{ fontFamily: mono, fontSize: 14, color: palette.inkFaint, marginTop: 18 }}>
          0 point discrepancies across all 732 games
        </div>
      </div>

      <div
        style={{
          position: 'absolute',
          left: 170,
          right: 170,
          top: 790,
          height: 1,
          background: palette.rule,
          opacity: between(frame, [620, 660], [0, 1]),
        }}
      >
        <div
          style={{
            height: 1,
            width: `${between(frame, [620, 808], [0, 100], easeInOut)}%`,
            background: palette.orange,
          }}
        />
      </div>
    </div>
  );
};

const Close: React.FC<{ frame: number }> = ({ frame }) => {
  const opacity = between(frame, [808, 810], [0, 1]);
  const y = between(frame, [810, 844], [54, 0]);
  const ruleWidth = between(frame, [816, 858], [0, 560], easeInOut);
  return (
    <div
      style={{
        position: 'absolute',
        inset: 0,
        background: palette.paperBright,
        opacity,
        display: 'flex',
        alignItems: 'center',
        transform: `translateY(${y}px)`,
      }}
    >
      <div style={{ marginLeft: 166, width: 1500 }}>
        <div style={{ width: ruleWidth, height: 4, background: palette.orange, marginBottom: 36 }} />
        <div
          style={{
            fontFamily: sans,
            fontSize: 108,
            lineHeight: 0.96,
            fontWeight: 600,
            color: palette.ink,
            letterSpacing: '-0.066em',
          }}
        >
          EuroLeague Analytics
        </div>
        <div
          style={{
            display: 'flex',
            alignItems: 'baseline',
            gap: 30,
            marginTop: 44,
          }}
        >
          <span style={{ fontFamily: sans, fontSize: 31, color: palette.inkSoft }}>Open source.</span>
          <span style={{ fontFamily: mono, fontSize: 18, color: palette.orange }}>
            github.com/egemeny13/euroleague-analytics
          </span>
        </div>
      </div>
    </div>
  );
};

export const CodexLaunch: React.FC = () => {
  const frame = useCurrentFrame();
  const cameraScale = between(
    frame,
    [0, 110, 300, 405, 530, 650, 805, 900],
    [0.985, 1.015, 1.035, 1.055, 1.075, 1.02, 0.98, 1],
    easeInOut
  );
  const cameraX = between(
    frame,
    [0, 300, 350, 405, 540, 650, 805],
    [0, 0, -54, -54, 0, 0, 0],
    easeInOut
  );
  const musicVolume = between(frame, [0, 24, 846, 900], [0, 0.72, 0.72, 0]);

  return (
    <AbsoluteFill style={{ background: palette.paper, overflow: 'hidden' }}>
      <FontFaces />
      <Audio src={staticFile('audio/codex-music.wav')} volume={musicVolume} />
      <Sequence from={132} durationInFrames={144}>
        <Audio src={staticFile('audio/codex-typing.wav')} volume={0.58} />
      </Sequence>
      <Sequence from={301} durationInFrames={16}>
        <Audio src={staticFile('audio/codex-enter.wav')} volume={0.8} />
      </Sequence>
      <Sequence from={405} durationInFrames={20}>
        <Audio src={staticFile('audio/codex-tool.wav')} volume={0.64} />
      </Sequence>
      <Sequence from={505} durationInFrames={24}>
        <Audio src={staticFile('audio/codex-swish.wav')} volume={0.44} />
      </Sequence>
      <Sequence from={596} durationInFrames={27}>
        <Audio src={staticFile('audio/codex-air.wav')} volume={0.46} />
      </Sequence>
      <Sequence from={804} durationInFrames={27}>
        <Audio src={staticFile('audio/codex-air.wav')} volume={0.38} />
      </Sequence>

      <div
        style={{
          position: 'absolute',
          inset: 0,
          transform: `translateX(${cameraX}px) scale(${cameraScale})`,
          transformOrigin: 'center center',
        }}
      >
        <CourtField frame={frame} />
        <EditorialHeader frame={frame} />
        <Hook frame={frame} />
        <Query frame={frame} />
        <Process frame={frame} />
        <Answer frame={frame} />
        <Proof frame={frame} />
        <AttentionTrace frame={frame} />
      </div>
      <Close frame={frame} />
    </AbsoluteFill>
  );
};
