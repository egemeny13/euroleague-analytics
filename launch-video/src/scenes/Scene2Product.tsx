import React from 'react';
import { interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion';
import { THEME } from '../design/theme';

export const Scene2Product: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Dynamic continuous camera motion
  const cameraScale = interpolate(frame, [0, 120], [0.97, 1.04], {
    extrapolateRight: 'clamp',
  });

  const badgeSpring = spring({
    frame: frame - 6,
    fps,
    config: { damping: 18, stiffness: 120 },
  });
  const badgeOpacity = interpolate(badgeSpring, [0, 1], [0, 1]);
  const badgeY = interpolate(badgeSpring, [0, 1], [14, 0]);

  const titleSpring = spring({
    frame: frame - 18,
    fps,
    config: { damping: 18, stiffness: 100 },
  });
  const titleOpacity = interpolate(titleSpring, [0, 1], [0, 1]);
  const titleY = interpolate(titleSpring, [0, 1], [22, 0]);

  const descSpring = spring({
    frame: frame - 38,
    fps,
    config: { damping: 18, stiffness: 90 },
  });
  const descOpacity = interpolate(descSpring, [0, 1], [0, 1]);
  const descY = interpolate(descSpring, [0, 1], [20, 0]);

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
        textAlign: 'center',
        transform: `scale(${cameraScale})`,
      }}
    >
      <div style={{ maxWidth: 1300 }}>
        {/* Category Tag */}
        <div
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 10,
            padding: '8px 20px',
            backgroundColor: THEME.colors.accentMuted,
            border: `1px solid ${THEME.colors.accentBorder}`,
            borderRadius: 6,
            marginBottom: 28,
            opacity: badgeOpacity,
            transform: `translateY(${badgeY}px)`,
          }}
        >
          <div
            style={{
              width: 8,
              height: 8,
              borderRadius: '50%',
              backgroundColor: THEME.colors.accent,
            }}
          />
          <span
            style={{
              fontFamily: THEME.fonts.mono,
              fontSize: 14,
              fontWeight: 700,
              color: THEME.colors.accent,
              letterSpacing: '0.08em',
              textTransform: 'uppercase',
            }}
          >
            Model Context Protocol &bull; Validated Warehouse
          </span>
        </div>

        {/* Product Brand Title */}
        <h1
          style={{
            fontFamily: THEME.fonts.sans,
            fontSize: 96,
            fontWeight: 800,
            color: THEME.colors.textPrimary,
            letterSpacing: '-0.04em',
            lineHeight: 1.05,
            margin: 0,
            opacity: titleOpacity,
            transform: `translateY(${titleY}px)`,
          }}
        >
          EuroLeague Analytics
        </h1>

        {/* Value Proposition */}
        <div
          style={{
            marginTop: 32,
            opacity: descOpacity,
            transform: `translateY(${descY}px)`,
          }}
        >
          <p
            style={{
              fontFamily: THEME.fonts.sans,
              fontSize: 44,
              fontWeight: 500,
              color: THEME.colors.textSecondary,
              letterSpacing: '-0.025em',
              lineHeight: 1.3,
              margin: 0,
            }}
          >
            Ask basketball questions from{' '}
            <span style={{ color: THEME.colors.textPrimary, fontWeight: 700 }}>
              possession-level data.
            </span>
          </p>
        </div>

        {/* Subtle Invariant Pillars */}
        <div
          style={{
            marginTop: 44,
            display: 'flex',
            justifyContent: 'center',
            alignItems: 'center',
            gap: 28,
            opacity: interpolate(
              spring({ frame: frame - 55, fps, config: { damping: 20 } }),
              [0, 1],
              [0, 1]
            ),
          }}
        >
          <span
            style={{
              fontFamily: THEME.fonts.mono,
              fontSize: 15,
              color: THEME.colors.textSecondary,
              letterSpacing: '0.02em',
            }}
          >
            Exact 5-Man Lineup Reconstruction
          </span>
          <span style={{ color: THEME.colors.borderStrong }}>&bull;</span>
          <span
            style={{
              fontFamily: THEME.fonts.mono,
              fontSize: 15,
              color: THEME.colors.textSecondary,
              letterSpacing: '0.02em',
            }}
          >
            Zero Box-Score Estimation Formulas
          </span>
        </div>
      </div>
    </div>
  );
};
