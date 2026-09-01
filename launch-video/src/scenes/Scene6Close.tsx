import React from 'react';
import { interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion';
import { THEME } from '../design/theme';

export const Scene6Close: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Dynamic subtle camera settle
  const cameraScale = interpolate(frame, [0, 180], [0.97, 1.03], {
    extrapolateRight: 'clamp',
  });

  const titleSpring = spring({
    frame: frame - 6,
    fps,
    config: { damping: 20, stiffness: 100 },
  });
  const titleOpacity = interpolate(titleSpring, [0, 1], [0, 1]);
  const titleY = interpolate(titleSpring, [0, 1], [16, 0]);

  const subSpring = spring({
    frame: frame - 22,
    fps,
    config: { damping: 20, stiffness: 100 },
  });
  const subOpacity = interpolate(subSpring, [0, 1], [0, 1]);

  const linkSpring = spring({
    frame: frame - 40,
    fps,
    config: { damping: 20, stiffness: 90 },
  });
  const linkOpacity = interpolate(linkSpring, [0, 1], [0, 1]);
  const linkY = interpolate(linkSpring, [0, 1], [14, 0]);

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
      <div style={{ maxWidth: 1000 }}>
        {/* Brand Title */}
        <h1
          style={{
            fontFamily: THEME.fonts.sans,
            fontSize: 84,
            fontWeight: 800,
            color: THEME.colors.textPrimary,
            letterSpacing: '-0.04em',
            lineHeight: 1.1,
            margin: 0,
            opacity: titleOpacity,
            transform: `translateY(${titleY}px)`,
          }}
        >
          EuroLeague Analytics
        </h1>

        {/* Subtitle */}
        <div
          style={{
            fontFamily: THEME.fonts.sans,
            fontSize: 30,
            fontWeight: 500,
            color: THEME.colors.textSecondary,
            marginTop: 18,
            opacity: subOpacity,
          }}
        >
          Open source basketball intelligence.
        </div>

        {/* Links / Monospace URLs */}
        <div
          style={{
            marginTop: 44,
            display: 'flex',
            flexDirection: 'column',
            gap: 14,
            alignItems: 'center',
            opacity: linkOpacity,
            transform: `translateY(${linkY}px)`,
          }}
        >
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 12,
              padding: '12px 28px',
              backgroundColor: THEME.colors.bgSurface,
              border: `1.5px solid ${THEME.colors.borderStrong}`,
              borderRadius: 8,
              boxShadow: '0 4px 16px rgba(15, 23, 42, 0.04)',
            }}
          >
            <span
              style={{
                fontFamily: THEME.fonts.mono,
                fontSize: 18,
                fontWeight: 700,
                color: THEME.colors.accent,
              }}
            >
              github.com/egemeny13/euroleague-analytics
            </span>
          </div>

          <div
            style={{
              fontFamily: THEME.fonts.mono,
              fontSize: 15,
              color: THEME.colors.textSecondary,
              letterSpacing: '0.04em',
            }}
          >
            egemenyucelen.me &bull; MIT License
          </div>
        </div>
      </div>
    </div>
  );
};
