import React from 'react';
import { interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion';
import { THEME } from '../design/theme';

export const Scene4Architecture: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const steps = [
    {
      num: '01',
      kicker: 'AI CLIENT / PROMPT',
      title: 'Natural Language Query',
      spec: 'Claude Desktop, Cursor, Custom Agents',
    },
    {
      num: '02',
      kicker: 'PROTOCOL LAYER',
      title: '11 MCP Tools',
      spec: 'Token-aware pagination &bull; readOnlyHint',
    },
    {
      num: '03',
      kicker: 'DERIVED WAREHOUSE',
      title: 'PostgreSQL & Invariants',
      spec: '5 possession ending rules &bull; 0 box-score guesses',
    },
    {
      num: '04',
      kicker: 'EVALUATION GATED',
      title: 'Verified Ground Truth',
      spec: 'Dual-path SQL & MCP agreement &bull; 100% score match',
    },
  ];

  const headerSpring = spring({
    frame: frame - 2,
    fps,
    config: { damping: 20, stiffness: 120 },
  });
  const headerOpacity = interpolate(headerSpring, [0, 1], [0, 1]);
  const headerY = interpolate(headerSpring, [0, 1], [14, 0]);

  // Track progress bar animation across frames 15 to 110
  const progressWidth = interpolate(frame, [15, 100], [0, 100], {
    extrapolateRight: 'clamp',
  });

  return (
    <div
      style={{
        width: '100%',
        height: '100%',
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'center',
        alignItems: 'center',
        padding: '0 120px',
      }}
    >
      <div style={{ width: '100%', maxWidth: 1440 }}>
        {/* Section Header */}
        <div
          style={{
            textAlign: 'center',
            marginBottom: 60,
            opacity: headerOpacity,
            transform: `translateY(${headerY}px)`,
          }}
        >
          <div
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 8,
              fontFamily: THEME.fonts.mono,
              fontSize: 13,
              fontWeight: 700,
              color: THEME.colors.accent,
              letterSpacing: '0.12em',
              textTransform: 'uppercase',
              marginBottom: 12,
            }}
          >
            <span style={{ color: THEME.colors.accent }}>//</span>
            <span>Zero Hallucination Architecture</span>
          </div>
          <h2
            style={{
              fontFamily: THEME.fonts.sans,
              fontSize: 48,
              fontWeight: 700,
              color: THEME.colors.textPrimary,
              letterSpacing: '-0.03em',
              margin: 0,
            }}
          >
            From Natural Language to Verified Basketball Data
          </h2>
        </div>

        {/* Pipeline Container with Animated Track Line */}
        <div style={{ position: 'relative' }}>
          {/* Background Track Line */}
          <div
            style={{
              position: 'absolute',
              top: 36,
              left: 40,
              right: 40,
              height: 2,
              backgroundColor: 'rgba(255, 255, 255, 0.08)',
              zIndex: 1,
            }}
          >
            {/* Active orange glow line */}
            <div
              style={{
                height: '100%',
                width: `${progressWidth}%`,
                backgroundColor: THEME.colors.accent,
                boxShadow: `0 0 12px ${THEME.colors.accent}`,
              }}
            />
          </div>

          {/* 4 Pipeline Stages */}
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(4, 1fr)',
              gap: 28,
              position: 'relative',
              zIndex: 2,
            }}
          >
            {steps.map((step, idx) => {
              const stepTrigger = 10 + idx * 18;
              const stepSpring = spring({
                frame: frame - stepTrigger,
                fps,
                config: { damping: 18, stiffness: 110 },
              });
              const opacity = interpolate(stepSpring, [0, 1], [0, 1]);
              const translateY = interpolate(stepSpring, [0, 1], [20, 0]);
              const isActive = frame >= stepTrigger;

              return (
                <div
                  key={idx}
                  style={{
                    opacity,
                    transform: `translateY(${translateY}px)`,
                    display: 'flex',
                    flexDirection: 'column',
                  }}
                >
                  {/* Step Node Dot */}
                  <div
                    style={{
                      width: 24,
                      height: 24,
                      borderRadius: '50%',
                      backgroundColor: isActive ? THEME.colors.accent : THEME.colors.bgSurface,
                      border: `3px solid ${THEME.colors.bg}`,
                      outline: `1px solid ${isActive ? THEME.colors.accent : THEME.colors.border}`,
                      marginBottom: 20,
                      transition: 'all 0.2s ease',
                      boxShadow: isActive ? `0 0 10px ${THEME.colors.accent}` : 'none',
                    }}
                  />

                  {/* Kicker */}
                  <span
                    style={{
                      fontFamily: THEME.fonts.mono,
                      fontSize: 11,
                      fontWeight: 700,
                      color: idx === 2 ? THEME.colors.accent : THEME.colors.textMuted,
                      letterSpacing: '0.1em',
                      marginBottom: 8,
                    }}
                  >
                    {step.kicker}
                  </span>

                  {/* Step Title */}
                  <h3
                    style={{
                      fontFamily: THEME.fonts.sans,
                      fontSize: 22,
                      fontWeight: 700,
                      color: THEME.colors.textPrimary,
                      letterSpacing: '-0.02em',
                      margin: '0 0 8px 0',
                      lineHeight: 1.25,
                    }}
                  >
                    {step.title}
                  </h3>

                  {/* Technical Spec */}
                  <p
                    dangerouslySetInnerHTML={{ __html: step.spec }}
                    style={{
                      fontFamily: THEME.fonts.mono,
                      fontSize: 13,
                      color: THEME.colors.textSecondary,
                      lineHeight: 1.45,
                      margin: 0,
                    }}
                  />
                </div>
              );
            })}
          </div>
        </div>

        {/* Footer Guarantee */}
        <div
          style={{
            marginTop: 56,
            display: 'flex',
            justifyContent: 'center',
            alignItems: 'center',
            gap: 20,
            opacity: interpolate(
              spring({ frame: frame - 80, fps, config: { damping: 20 } }),
              [0, 1],
              [0, 1]
            ),
          }}
        >
          <span
            style={{
              fontFamily: THEME.fonts.mono,
              fontSize: 13,
              color: THEME.colors.textMuted,
            }}
          >
            Pre-computed views query under 90ms &bull; Immutable checksummed raw archive &bull; Zero external wrapper deps
          </span>
        </div>
      </div>
    </div>
  );
};
