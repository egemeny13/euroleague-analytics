import React from 'react';
import { interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion';
import { THEME } from '../design/theme';

export const Scene3RealQuery: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Phase 1: Question Entrance (Frames 0–45)
  const questionSpring = spring({
    frame: frame - 4,
    fps,
    config: { damping: 20, stiffness: 110 },
  });
  const questionOpacity = interpolate(questionSpring, [0, 1], [0, 1]);
  const questionY = interpolate(questionSpring, [0, 1], [16, 0]);

  // Phase 2: MCP Tool Call (Frames 35–85)
  const toolSpring = spring({
    frame: frame - 35,
    fps,
    config: { damping: 20, stiffness: 120 },
  });
  const toolOpacity = interpolate(toolSpring, [0, 1], [0, 1]);
  const toolY = interpolate(toolSpring, [0, 1], [14, 0]);

  // Phase 3: Hero Data Split Card Reveal (Frames 75–270)
  const heroSpring = spring({
    frame: frame - 75,
    fps,
    config: { damping: 18, stiffness: 95 },
  });
  const heroOpacity = interpolate(heroSpring, [0, 1], [0, 1]);
  const heroY = interpolate(heroSpring, [0, 1], [24, 0]);

  // Staggered On / Off columns
  const onColSpring = spring({
    frame: frame - 85,
    fps,
    config: { damping: 16, stiffness: 100 },
  });
  const offColSpring = spring({
    frame: frame - 105,
    fps,
    config: { damping: 16, stiffness: 100 },
  });

  // Footer / Swing differential badge
  const diffSpring = spring({
    frame: frame - 130,
    fps,
    config: { damping: 18, stiffness: 110 },
  });
  const diffOpacity = interpolate(diffSpring, [0, 1], [0, 1]);

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
      }}
    >
      <div style={{ width: '100%', maxWidth: 1440 }}>
        {/* Natural Language Prompt Box */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 16,
            marginBottom: 20,
            opacity: questionOpacity,
            transform: `translateY(${questionY}px)`,
          }}
        >
          <div
            style={{
              padding: '6px 12px',
              backgroundColor: 'rgba(255, 255, 255, 0.08)',
              border: `1px solid ${THEME.colors.border}`,
              borderRadius: 4,
              fontFamily: THEME.fonts.mono,
              fontSize: 13,
              fontWeight: 700,
              color: THEME.colors.accent,
              textTransform: 'uppercase',
              letterSpacing: '0.08em',
            }}
          >
            Query
          </div>
          <h2
            style={{
              fontFamily: THEME.fonts.sans,
              fontSize: 34,
              fontWeight: 700,
              color: THEME.colors.textPrimary,
              letterSpacing: '-0.02em',
              margin: 0,
            }}
          >
            "How did Paris perform with TJ Shorts on vs. off the floor?"
          </h2>
        </div>

        {/* MCP Tool Invocation Snippet */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '12px 22px',
            backgroundColor: THEME.colors.bgSurface,
            border: `1px solid ${THEME.colors.border}`,
            borderLeft: `3px solid ${THEME.colors.accent}`,
            borderRadius: 6,
            marginBottom: 34,
            opacity: toolOpacity,
            transform: `translateY(${toolY}px)`,
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <span
              style={{
                fontFamily: THEME.fonts.mono,
                fontSize: 14,
                color: THEME.colors.accent,
                fontWeight: 700,
              }}
            >
              mcp://
            </span>
            <span
              style={{
                fontFamily: THEME.fonts.mono,
                fontSize: 15,
                color: THEME.colors.textPrimary,
                fontWeight: 500,
              }}
            >
              el_get_on_off_splits
              <span style={{ color: THEME.colors.textSecondary }}>
                (season: "E2024", player: "SHORTS, TJ", team: "PRS")
              </span>
            </span>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <div
              style={{
                width: 7,
                height: 7,
                borderRadius: '50%',
                backgroundColor: THEME.colors.positive,
              }}
            />
            <span
              style={{
                fontFamily: THEME.fonts.mono,
                fontSize: 13,
                fontWeight: 600,
                color: THEME.colors.positive,
              }}
            >
              2,488 possessions matched
            </span>
          </div>
        </div>

        {/* Hero Data Comparison (The Centerpiece) */}
        <div
          style={{
            opacity: heroOpacity,
            transform: `translateY(${heroY}px)`,
          }}
        >
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: '1fr 1fr',
              gap: 32,
            }}
          >
            {/* ON COURT SPLIT */}
            <div
              style={{
                backgroundColor: THEME.colors.bgCard,
                border: `1px solid ${THEME.colors.borderStrong}`,
                borderRadius: 8,
                padding: '36px 44px',
                position: 'relative',
                transform: `scale(${interpolate(onColSpring, [0, 1], [0.97, 1])})`,
                opacity: interpolate(onColSpring, [0, 1], [0, 1]),
              }}
            >
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'baseline',
                  marginBottom: 16,
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <div
                    style={{
                      width: 10,
                      height: 10,
                      borderRadius: 2,
                      backgroundColor: THEME.colors.positive,
                    }}
                  />
                  <span
                    style={{
                      fontFamily: THEME.fonts.mono,
                      fontSize: 16,
                      fontWeight: 700,
                      color: THEME.colors.textPrimary,
                      letterSpacing: '0.08em',
                      textTransform: 'uppercase',
                    }}
                  >
                    ON COURT
                  </span>
                </div>
                <span
                  style={{
                    fontFamily: THEME.fonts.mono,
                    fontSize: 14,
                    color: THEME.colors.textMuted,
                  }}
                >
                  1,667 possessions &bull; 34 games
                </span>
              </div>

              {/* Net Rating Big Stat */}
              <div
                style={{
                  fontFamily: THEME.fonts.mono,
                  fontSize: 80,
                  fontWeight: 800,
                  color: THEME.colors.positive,
                  letterSpacing: '-0.04em',
                  lineHeight: 1,
                  margin: '12px 0 20px',
                }}
              >
                +5.09
                <span
                  style={{
                    fontSize: 22,
                    fontWeight: 700,
                    color: THEME.colors.textSecondary,
                    marginLeft: 14,
                    letterSpacing: '0.04em',
                  }}
                >
                  NET RTG
                </span>
              </div>

              {/* Four Factors Breakdown */}
              <div
                style={{
                  display: 'flex',
                  gap: 36,
                  paddingTop: 18,
                  borderTop: `1px solid ${THEME.colors.border}`,
                }}
              >
                <div>
                  <div
                    style={{
                      fontFamily: THEME.fonts.mono,
                      fontSize: 12,
                      fontWeight: 600,
                      color: THEME.colors.textMuted,
                      textTransform: 'uppercase',
                    }}
                  >
                    Offensive Rtg
                  </div>
                  <div
                    style={{
                      fontFamily: THEME.fonts.mono,
                      fontSize: 24,
                      fontWeight: 700,
                      color: THEME.colors.textPrimary,
                      marginTop: 4,
                    }}
                  >
                    116.14
                  </div>
                </div>
                <div>
                  <div
                    style={{
                      fontFamily: THEME.fonts.mono,
                      fontSize: 12,
                      fontWeight: 600,
                      color: THEME.colors.textMuted,
                      textTransform: 'uppercase',
                    }}
                  >
                    Defensive Rtg
                  </div>
                  <div
                    style={{
                      fontFamily: THEME.fonts.mono,
                      fontSize: 24,
                      fontWeight: 700,
                      color: THEME.colors.textPrimary,
                      marginTop: 4,
                    }}
                  >
                    111.04
                  </div>
                </div>
                <div>
                  <div
                    style={{
                      fontFamily: THEME.fonts.mono,
                      fontSize: 12,
                      fontWeight: 600,
                      color: THEME.colors.textMuted,
                      textTransform: 'uppercase',
                    }}
                  >
                    Points For/Against
                  </div>
                  <div
                    style={{
                      fontFamily: THEME.fonts.mono,
                      fontSize: 24,
                      fontWeight: 700,
                      color: THEME.colors.textSecondary,
                      marginTop: 4,
                    }}
                  >
                    1,936 / 1,850
                  </div>
                </div>
              </div>
            </div>

            {/* OFF COURT SPLIT */}
            <div
              style={{
                backgroundColor: THEME.colors.bgCard,
                border: `1px solid ${THEME.colors.borderStrong}`,
                borderRadius: 8,
                padding: '36px 44px',
                position: 'relative',
                transform: `scale(${interpolate(offColSpring, [0, 1], [0.97, 1])})`,
                opacity: interpolate(offColSpring, [0, 1], [0, 1]),
              }}
            >
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'baseline',
                  marginBottom: 16,
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <div
                    style={{
                      width: 10,
                      height: 10,
                      borderRadius: 2,
                      backgroundColor: THEME.colors.negative,
                    }}
                  />
                  <span
                    style={{
                      fontFamily: THEME.fonts.mono,
                      fontSize: 16,
                      fontWeight: 700,
                      color: THEME.colors.textPrimary,
                      letterSpacing: '0.08em',
                      textTransform: 'uppercase',
                    }}
                  >
                    OFF COURT
                  </span>
                </div>
                <span
                  style={{
                    fontFamily: THEME.fonts.mono,
                    fontSize: 14,
                    color: THEME.colors.textMuted,
                  }}
                >
                  821 possessions &bull; 34 games
                </span>
              </div>

              {/* Net Rating Big Stat */}
              <div
                style={{
                  fontFamily: THEME.fonts.mono,
                  fontSize: 80,
                  fontWeight: 800,
                  color: THEME.colors.negative,
                  letterSpacing: '-0.04em',
                  lineHeight: 1,
                  margin: '12px 0 20px',
                }}
              >
                -11.45
                <span
                  style={{
                    fontSize: 22,
                    fontWeight: 700,
                    color: THEME.colors.textSecondary,
                    marginLeft: 14,
                    letterSpacing: '0.04em',
                  }}
                >
                  NET RTG
                </span>
              </div>

              {/* Four Factors Breakdown */}
              <div
                style={{
                  display: 'flex',
                  gap: 36,
                  paddingTop: 18,
                  borderTop: `1px solid ${THEME.colors.border}`,
                }}
              >
                <div>
                  <div
                    style={{
                      fontFamily: THEME.fonts.mono,
                      fontSize: 12,
                      fontWeight: 600,
                      color: THEME.colors.textMuted,
                      textTransform: 'uppercase',
                    }}
                  >
                    Offensive Rtg
                  </div>
                  <div
                    style={{
                      fontFamily: THEME.fonts.mono,
                      fontSize: 24,
                      fontWeight: 700,
                      color: THEME.colors.textPrimary,
                      marginTop: 4,
                    }}
                  >
                    117.05
                  </div>
                </div>
                <div>
                  <div
                    style={{
                      fontFamily: THEME.fonts.mono,
                      fontSize: 12,
                      fontWeight: 600,
                      color: THEME.colors.textMuted,
                      textTransform: 'uppercase',
                    }}
                  >
                    Defensive Rtg
                  </div>
                  <div
                    style={{
                      fontFamily: THEME.fonts.mono,
                      fontSize: 24,
                      fontWeight: 700,
                      color: THEME.colors.textPrimary,
                      marginTop: 4,
                    }}
                  >
                    128.50
                  </div>
                </div>
                <div>
                  <div
                    style={{
                      fontFamily: THEME.fonts.mono,
                      fontSize: 12,
                      fontWeight: 600,
                      color: THEME.colors.textMuted,
                      textTransform: 'uppercase',
                    }}
                  >
                    Points For/Against
                  </div>
                  <div
                    style={{
                      fontFamily: THEME.fonts.mono,
                      fontSize: 24,
                      fontWeight: 700,
                      color: THEME.colors.textSecondary,
                      marginTop: 4,
                    }}
                  >
                    961 / 1,064
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Differential Callout */}
          <div
            style={{
              marginTop: 24,
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              padding: '14px 24px',
              backgroundColor: 'rgba(255, 255, 255, 0.03)',
              border: `1px solid ${THEME.colors.border}`,
              borderRadius: 6,
              opacity: diffOpacity,
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <span
                style={{
                  fontFamily: THEME.fonts.mono,
                  fontSize: 14,
                  fontWeight: 800,
                  color: THEME.colors.accent,
                }}
              >
                SWING: +16.54 NET RATING DIFFERENTIAL
              </span>
              <span style={{ color: THEME.colors.textMuted }}>&bull;</span>
              <span
                style={{
                  fontFamily: THEME.fonts.sans,
                  fontSize: 14,
                  color: THEME.colors.textSecondary,
                }}
              >
                Paris defense collapses by +17.46 points allowed per 100 without Shorts
              </span>
            </div>

            <span
              style={{
                fontFamily: THEME.fonts.mono,
                fontSize: 12,
                color: THEME.colors.textMuted,
              }}
            >
              Source: evaluation.xml #2 &bull; 0 Point Reconciliation Discrepancy
            </span>
          </div>
        </div>
      </div>
    </div>
  );
};
