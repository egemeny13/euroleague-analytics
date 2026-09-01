import React from 'react';
import { interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion';
import { THEME } from '../design/theme';

export const Scene1Hook: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Dynamic camera scale push-in
  const cameraScale = interpolate(frame, [0, 120], [0.97, 1.04], {
    extrapolateRight: 'clamp',
  });

  // Line 1 Reveal: "EuroLeague data is everywhere." (Frames 8–40)
  const spring1 = spring({
    frame: frame - 8,
    fps,
    config: { damping: 18, stiffness: 100, mass: 0.8 },
  });
  const opacity1 = interpolate(spring1, [0, 1], [0, 1]);
  const y1 = interpolate(spring1, [0, 1], [20, 0]);

  // Line 2 Reveal: "Good answers are harder." (Frames 48–80)
  const spring2 = spring({
    frame: frame - 48,
    fps,
    config: { damping: 18, stiffness: 100, mass: 0.8 },
  });
  const opacity2 = interpolate(spring2, [0, 1], [0, 1]);
  const y2 = interpolate(spring2, [0, 1], [24, 0]);

  // Accent line growth
  const lineWidth = interpolate(frame, [56, 95], [0, 96], {
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
        textAlign: 'center',
        transform: `scale(${cameraScale})`,
      }}
    >
      <div style={{ maxWidth: 1300 }}>
        {/* Line 1 */}
        <h1
          style={{
            fontFamily: THEME.fonts.sans,
            fontSize: 68,
            fontWeight: 500,
            color: THEME.colors.textSecondary,
            letterSpacing: '-0.03em',
            lineHeight: 1.15,
            opacity: opacity1,
            transform: `translateY(${y1}px)`,
            margin: 0,
          }}
        >
          EuroLeague data is everywhere.
        </h1>

        {/* Line 2 */}
        <h2
          style={{
            fontFamily: THEME.fonts.sans,
            fontSize: 84,
            fontWeight: 800,
            color: THEME.colors.textPrimary,
            letterSpacing: '-0.04em',
            lineHeight: 1.15,
            opacity: opacity2,
            transform: `translateY(${y2}px)`,
            marginTop: 20,
            marginBottom: 36,
          }}
        >
          Good answers are harder.
        </h2>

        {/* Minimal accent bar */}
        <div
          style={{
            height: 3,
            width: lineWidth,
            backgroundColor: THEME.colors.accent,
            margin: '0 auto',
            borderRadius: 2,
          }}
        />
      </div>
    </div>
  );
};
