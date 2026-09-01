import React from 'react';
import { interpolate, useCurrentFrame } from 'remotion';
import { THEME } from './theme';

interface CourtBackgroundProps {
  opacity?: number;
}

export const CourtBackground: React.FC<CourtBackgroundProps> = ({ opacity = 1 }) => {
  const frame = useCurrentFrame();

  // Subtle continuous camera drift
  const scale = interpolate(frame, [0, 900], [1.0, 1.06], {
    extrapolateRight: 'clamp',
  });

  return (
    <div
      style={{
        position: 'absolute',
        inset: 0,
        backgroundColor: THEME.colors.bg,
        overflow: 'hidden',
        zIndex: 0,
      }}
    >
      {/* Subtle background technical grid */}
      <div
        style={{
          position: 'absolute',
          inset: 0,
          backgroundImage: `
            linear-gradient(to right, rgba(15, 23, 42, 0.025) 1px, transparent 1px),
            linear-gradient(to bottom, rgba(15, 23, 42, 0.025) 1px, transparent 1px)
          `,
          backgroundSize: '48px 48px',
          opacity: opacity * 0.8,
        }}
      />

      {/* Centered Half Court Vector Graphics in Light Mode */}
      <div
        style={{
          position: 'absolute',
          left: '50%',
          top: '50%',
          transform: `translate(-50%, -50%) scale(${scale})`,
          width: 1200,
          height: 960,
          pointerEvents: 'none',
          opacity: opacity * 0.07,
        }}
      >
        <svg
          viewBox="0 0 1200 960"
          width="1200"
          height="960"
          fill="none"
          stroke={THEME.colors.textPrimary}
          strokeWidth="1.5"
        >
          {/* Baseline & Court Border */}
          <rect x="50" y="50" width="1100" height="860" strokeWidth="2" />

          {/* Key / Paint */}
          <rect x="410" y="50" width="380" height="440" strokeWidth="1.5" />

          {/* Free throw circle */}
          <path d="M 460 490 A 140 140 0 0 0 740 490" strokeWidth="1.5" />
          <path
            d="M 460 490 A 140 140 0 0 1 740 490"
            strokeWidth="1.5"
            strokeDasharray="8 8"
          />

          {/* Restricted Area Arc */}
          <path d="M 505 130 A 55 55 0 0 0 615 130" strokeWidth="1.5" />

          {/* Backboard & Hoop */}
          <line x1="510" y1="90" x2="610" y2="90" stroke={THEME.colors.accent} strokeWidth="3" />
          <circle cx="560" cy="110" r="15" stroke={THEME.colors.accent} strokeWidth="2" />

          {/* 3-Point Line */}
          <path
            d="
              M 130 50 
              L 130 230 
              A 470 470 0 0 0 1070 230 
              L 1070 50
            "
            strokeWidth="1.8"
          />

          {/* Center Court Circle */}
          <path d="M 450 910 A 150 150 0 0 1 750 910" strokeWidth="1.5" />
        </svg>
      </div>

      {/* Radial center highlight for ultra-crisp editorial reading */}
      <div
        style={{
          position: 'absolute',
          inset: 0,
          background: 'radial-gradient(ellipse at center, rgba(248, 250, 252, 0.94) 30%, rgba(248, 250, 252, 0.7) 75%, rgba(248, 250, 252, 0.98) 100%)',
          pointerEvents: 'none',
        }}
      />
    </div>
  );
};
