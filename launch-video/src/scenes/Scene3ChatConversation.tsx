import React from 'react';
import { interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion';
import { THEME } from '../design/theme';

export const Scene3ChatConversation: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Full question string for typewriter effect
  const fullQuery = 'How did Paris perform with TJ Shorts on vs. off the floor in E2024?';
  
  // Typewriter timing: frames 12 to 68
  const typedCharCount = Math.floor(
    interpolate(frame, [12, 68], [0, fullQuery.length], {
      extrapolateLeft: 'clamp',
      extrapolateRight: 'clamp',
    })
  );
  const displayedQuery = fullQuery.slice(0, typedCharCount);

  // Blinking cursor
  const showCursor = frame < 75 && Math.floor(frame / 6) % 2 === 0;

  // Dynamic Camera Push-In throughout the conversation
  const cameraScale = interpolate(frame, [0, 100, 300], [0.98, 1.01, 1.06], {
    extrapolateRight: 'clamp',
  });

  // Prompt Box position: starts slightly lower, smoothly moves to top anchor when thinking begins
  const promptShiftSpring = spring({
    frame: frame - 72,
    fps,
    config: { damping: 20, stiffness: 90 },
  });
  const promptOffsetY = interpolate(promptShiftSpring, [0, 1], [60, 0]);

  // Thinking State animation (Frames 72–110)
  const isThinking = frame >= 72 && frame < 110;
  const thinkingDotPhase = Math.floor((frame - 72) / 7) % 3;

  // Tool Call pill animation (Reveals around frame 82)
  const toolSpring = spring({
    frame: frame - 80,
    fps,
    config: { damping: 18, stiffness: 120 },
  });
  const toolOpacity = interpolate(toolSpring, [0, 1], [0, 1]);
  const toolY = interpolate(toolSpring, [0, 1], [10, 0]);

  // Answer payload entrance (Frames 106–300)
  const answerSpring = spring({
    frame: frame - 106,
    fps,
    config: { damping: 16, stiffness: 95, mass: 0.9 },
  });
  const answerOpacity = interpolate(answerSpring, [0, 1], [0, 1]);
  const answerY = interpolate(answerSpring, [0, 1], [24, 0]);

  // Staggered on/off columns
  const onColSpring = spring({
    frame: frame - 114,
    fps,
    config: { damping: 15, stiffness: 110 },
  });
  const offColSpring = spring({
    frame: frame - 128,
    fps,
    config: { damping: 15, stiffness: 110 },
  });

  // Swing footer badge
  const swingSpring = spring({
    frame: frame - 150,
    fps,
    config: { damping: 18, stiffness: 110 },
  });
  const swingOpacity = interpolate(swingSpring, [0, 1], [0, 1]);

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
      <div style={{ width: '100%', maxWidth: 1440, transform: `translateY(${promptOffsetY}px)` }}>
        {/* 1. User Prompt Input Box */}
        <div
          style={{
            backgroundColor: THEME.colors.bgSurface,
            border: `1.5px solid ${THEME.colors.borderStrong}`,
            borderRadius: 10,
            padding: '20px 28px',
            boxShadow: '0 6px 24px rgba(15, 23, 42, 0.05)',
            marginBottom: 20,
            display: 'flex',
            alignItems: 'center',
            gap: 16,
          }}
        >
          <div
            style={{
              padding: '5px 12px',
              backgroundColor: THEME.colors.accentMuted,
              border: `1px solid ${THEME.colors.accentBorder}`,
              borderRadius: 4,
              fontFamily: THEME.fonts.mono,
              fontSize: 12,
              fontWeight: 700,
              color: THEME.colors.accent,
              textTransform: 'uppercase',
              letterSpacing: '0.08em',
            }}
          >
            Prompt
          </div>

          <div
            style={{
              fontFamily: THEME.fonts.sans,
              fontSize: 32,
              fontWeight: 600,
              color: THEME.colors.textPrimary,
              letterSpacing: '-0.02em',
              lineHeight: 1.2,
              flex: 1,
            }}
          >
            "{displayedQuery}"
            {showCursor && (
              <span style={{ color: THEME.colors.accent, fontWeight: 300 }}>|</span>
            )}
          </div>
        </div>

        {/* 2. Process & MCP Tool Indicator */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '10px 20px',
            backgroundColor: 'rgba(255, 255, 255, 0.9)',
            border: `1px solid ${THEME.colors.border}`,
            borderLeft: `3px solid ${THEME.colors.accent}`,
            borderRadius: 6,
            marginBottom: 28,
            minHeight: 44,
            opacity: isThinking || frame >= 106 ? 1 : 0,
            transition: 'opacity 0.2s ease',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <span
              style={{
                fontFamily: THEME.fonts.mono,
                fontSize: 13,
                color: THEME.colors.accent,
                fontWeight: 700,
              }}
            >
              mcp://
            </span>
            <span
              style={{
                fontFamily: THEME.fonts.mono,
                fontSize: 14,
                color: THEME.colors.textPrimary,
                fontWeight: 600,
              }}
            >
              el_get_on_off_splits
              <span style={{ color: THEME.colors.textSecondary, fontWeight: 400 }}>
                (season: "E2024", player: "SHORTS, TJ", team: "PRS")
              </span>
            </span>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            {isThinking ? (
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <span
                  style={{
                    fontFamily: THEME.fonts.mono,
                    fontSize: 12,
                    color: THEME.colors.accent,
                    fontWeight: 600,
                  }}
                >
                  Querying Warehouse
                </span>
                <span style={{ color: THEME.colors.accent, letterSpacing: '2px', fontWeight: 800 }}>
                  {thinkingDotPhase === 0 ? '•  ' : thinkingDotPhase === 1 ? '•• ' : '•••'}
                </span>
              </div>
            ) : (
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, opacity: toolOpacity, transform: `translateY(${toolY}px)` }}>
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
                  2,488 possessions verified
                </span>
              </div>
            )}
          </div>
        </div>

        {/* 3. Hero Answer Data Presentation */}
        <div
          style={{
            opacity: answerOpacity,
            transform: `translateY(${answerY}px)`,
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
                backgroundColor: THEME.colors.bgSurface,
                border: `1.5px solid ${THEME.colors.borderStrong}`,
                borderRadius: 10,
                padding: '34px 42px',
                boxShadow: '0 6px 24px rgba(15, 23, 42, 0.04)',
                transform: `scale(${interpolate(onColSpring, [0, 1], [0.96, 1])})`,
                opacity: interpolate(onColSpring, [0, 1], [0, 1]),
              }}
            >
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'baseline',
                  marginBottom: 12,
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
                      fontWeight: 800,
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
                    color: THEME.colors.textSecondary,
                  }}
                >
                  1,667 possessions &bull; 34 games
                </span>
              </div>

              {/* Net Rating Big Stat */}
              <div
                style={{
                  fontFamily: THEME.fonts.mono,
                  fontSize: 78,
                  fontWeight: 800,
                  color: THEME.colors.positive,
                  letterSpacing: '-0.04em',
                  lineHeight: 1,
                  margin: '10px 0 18px',
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
                  paddingTop: 16,
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
                backgroundColor: THEME.colors.bgSurface,
                border: `1.5px solid ${THEME.colors.borderStrong}`,
                borderRadius: 10,
                padding: '34px 42px',
                boxShadow: '0 6px 24px rgba(15, 23, 42, 0.04)',
                transform: `scale(${interpolate(offColSpring, [0, 1], [0.96, 1])})`,
                opacity: interpolate(offColSpring, [0, 1], [0, 1]),
              }}
            >
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'baseline',
                  marginBottom: 12,
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
                      fontWeight: 800,
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
                    color: THEME.colors.textSecondary,
                  }}
                >
                  821 possessions &bull; 34 games
                </span>
              </div>

              {/* Net Rating Big Stat */}
              <div
                style={{
                  fontFamily: THEME.fonts.mono,
                  fontSize: 78,
                  fontWeight: 800,
                  color: THEME.colors.negative,
                  letterSpacing: '-0.04em',
                  lineHeight: 1,
                  margin: '10px 0 18px',
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
                  paddingTop: 16,
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
              marginTop: 22,
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              padding: '14px 24px',
              backgroundColor: 'rgba(255, 255, 255, 0.9)',
              border: `1.5px solid ${THEME.colors.borderStrong}`,
              borderRadius: 8,
              opacity: swingOpacity,
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
                Paris defense collapses by +17.46 points allowed per 100 with Shorts on bench
              </span>
            </div>

            <span
              style={{
                fontFamily: THEME.fonts.mono,
                fontSize: 12,
                color: THEME.colors.textMuted,
              }}
            >
              Source: evaluation.xml #2 &bull; 0 Point Discrepancy
            </span>
          </div>
        </div>
      </div>
    </div>
  );
};
