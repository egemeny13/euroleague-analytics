import React from 'react';
import { interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion';
import { THEME } from '../design/theme';

export const Scene5Proof: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Dynamic continuous camera motion
  const cameraScale = interpolate(frame, [0, 180], [0.97, 1.04], {
    extrapolateRight: 'clamp',
  });

  const stats = [
    {
      value: '732',
      unit: 'GAMES',
      label: 'Public Games Loaded',
      detail: '330 in E2024 &bull; 402 in E2025',
      frameTrigger: 6,
    },
    {
      value: '107,311',
      unit: 'POSSESSIONS',
      label: 'Reconstructed Possessions',
      detail: '5 verified criteria &bull; Zero box-score guesses',
      frameTrigger: 45,
    },
    {
      value: '100.0%',
      unit: 'RECONCILED',
      label: 'Score Reconciliation',
      detail: '0 point discrepancies across all 732 games',
      frameTrigger: 85,
    },
  ];

  return (
    <div
      style={{
        width: '100%',
        height: '100%',
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'center',
        alignItems: 'center',
        padding: '0 100px',
        transform: `scale(${cameraScale})`,
      }}
    >
      <div style={{ width: '100%', maxWidth: 1440 }}>
        {/* Subtle section kicker */}
        <div
          style={{
            fontFamily: THEME.fonts.mono,
            fontSize: 13,
            fontWeight: 700,
            color: THEME.colors.accent,
            letterSpacing: '0.12em',
            textTransform: 'uppercase',
            marginBottom: 28,
            textAlign: 'center',
          }}
        >
          Ground Truth Provenance &bull; Invariant Gated
        </div>

        {/* 3 Monumental Column Grid */}
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(3, 1fr)',
            gap: 28,
          }}
        >
          {stats.map((stat, idx) => {
            const statSpring = spring({
              frame: frame - stat.frameTrigger,
              fps,
              config: { damping: 14, stiffness: 140, mass: 0.7 },
            });
            const opacity = interpolate(statSpring, [0, 1], [0, 1]);
            const scale = interpolate(statSpring, [0, 1], [0.93, 1]);
            const translateY = interpolate(statSpring, [0, 1], [20, 0]);

            return (
              <div
                key={idx}
                style={{
                  backgroundColor: THEME.colors.bgSurface,
                  border: `1.5px solid ${THEME.colors.borderStrong}`,
                  borderRadius: 10,
                  padding: '40px 36px',
                  boxShadow: '0 4px 20px rgba(15, 23, 42, 0.04)',
                  opacity,
                  transform: `scale(${scale}) translateY(${translateY}px)`,
                  display: 'flex',
                  flexDirection: 'column',
                  justifyContent: 'center',
                }}
              >
                {/* Large Stat Number */}
                <div
                  style={{
                    fontFamily: THEME.fonts.mono,
                    fontSize: 58,
                    fontWeight: 800,
                    color: THEME.colors.textPrimary,
                    letterSpacing: '-0.04em',
                    lineHeight: 1.05,
                    display: 'flex',
                    alignItems: 'baseline',
                    gap: 10,
                  }}
                >
                  <span>{stat.value}</span>
                  <span
                    style={{
                      fontSize: 18,
                      fontWeight: 700,
                      color: THEME.colors.accent,
                      letterSpacing: '0.06em',
                    }}
                  >
                    {stat.unit}
                  </span>
                </div>

                {/* Stat Label */}
                <div
                  style={{
                    fontFamily: THEME.fonts.sans,
                    fontSize: 21,
                    fontWeight: 700,
                    color: THEME.colors.textPrimary,
                    marginTop: 14,
                  }}
                >
                  {stat.label}
                </div>

                {/* Sub Detail */}
                <div
                  dangerouslySetInnerHTML={{ __html: stat.detail }}
                  style={{
                    fontFamily: THEME.fonts.mono,
                    fontSize: 13,
                    color: THEME.colors.textSecondary,
                    marginTop: 8,
                    lineHeight: 1.4,
                  }}
                />
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
};
