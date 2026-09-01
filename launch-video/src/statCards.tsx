import React from 'react';
import { AbsoluteFill, staticFile } from 'remotion';

// ============================================================================
// WEBPAGE DESIGN SYSTEM TOKENS (Strictly from site/style.css)
// ============================================================================
const tokens = {
  bgPage: '#F9F9FA',
  surface: '#FFFFFF',
  surfaceSubtle: '#F0F1F4',
  textPrimary: '#121316',
  textSecondary: '#61656E',
  textMuted: '#94979E',
  orangeAccent: '#E2541A',
  orangeTint: '#FDF3EE',
  orangeBorder: 'rgba(226, 84, 26, 0.22)',
  divider: '#E5E6EA',
  greenIndicator: '#22C55E',
};

const sans = "'Instrument Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif";
const mono = "'IBM Plex Mono', ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace";

const FontFaces: React.FC = () => (
  <style>{`
    @font-face {
      font-family: 'Instrument Sans';
      src: url('${staticFile('fonts/InstrumentSans-Regular.woff2')}') format('woff2');
      font-weight: 400;
    }
    @font-face {
      font-family: 'Instrument Sans';
      src: url('${staticFile('fonts/InstrumentSans-SemiBold.woff2')}') format('woff2');
      font-weight: 600;
    }
    @font-face {
      font-family: 'Instrument Sans';
      src: url('${staticFile('fonts/InstrumentSans-Bold.woff2')}') format('woff2');
      font-weight: 700;
    }
    @font-face {
      font-family: 'IBM Plex Mono';
      src: url('${staticFile('fonts/IBMPlexMono-Regular.ttf')}') format('truetype');
      font-weight: 400;
    }
    @font-face {
      font-family: 'IBM Plex Mono';
      src: url('${staticFile('fonts/IBMPlexMono-Medium.ttf')}') format('truetype');
      font-weight: 500;
    }
  `}</style>
);

// High-Fidelity Website Card Wrapper
const WebsiteCardFrame: React.FC<{
  badgeText: string;
  title: string;
  subtitle?: string;
  rightBadge?: React.ReactNode;
  footnote: string;
  children: React.ReactNode;
}> = ({ badgeText, title, subtitle, rightBadge, footnote, children }) => {
  return (
    <AbsoluteFill
      style={{
        background: tokens.bgPage,
        fontFamily: sans,
        padding: '44px 52px',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      <FontFaces />
      <div
        style={{
          flex: 1,
          background: tokens.surface,
          border: `1px solid ${tokens.divider}`,
          borderRadius: 14,
          boxShadow: '0 8px 30px rgba(18, 19, 22, 0.04)',
          padding: '40px 48px',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'space-between',
        }}
      >
        {/* Top Tag & Title */}
        <div>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <div style={{ width: 8, height: 8, borderRadius: '50%', background: tokens.orangeAccent }} />
              <span
                style={{
                  fontFamily: mono,
                  fontSize: 12,
                  color: tokens.orangeAccent,
                  textTransform: 'uppercase',
                  letterSpacing: '0.1em',
                  fontWeight: 600,
                  background: tokens.orangeTint,
                  border: `1px solid ${tokens.orangeBorder}`,
                  padding: '3px 10px',
                  borderRadius: 4,
                }}
              >
                {badgeText}
              </span>
            </div>
            {rightBadge && <div>{rightBadge}</div>}
          </div>

          <h1
            style={{
              fontSize: 34,
              fontWeight: 700,
              color: tokens.textPrimary,
              letterSpacing: '-0.035em',
              lineHeight: 1.15,
            }}
          >
            {title}
          </h1>
          {subtitle && (
            <p style={{ fontSize: 16, color: tokens.textSecondary, marginTop: 6, lineHeight: 1.4 }}>
              {subtitle}
            </p>
          )}
        </div>

        {/* Center Graphic Body */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'center', margin: '20px 0' }}>
          {children}
        </div>

        {/* Bottom Footnote */}
        <div
          style={{
            borderTop: `1px solid ${tokens.divider}`,
            paddingTop: 16,
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
          }}
        >
          <div style={{ fontSize: 13, color: tokens.textSecondary }}>
            {footnote}
          </div>
          <div style={{ fontFamily: mono, fontSize: 13, color: tokens.orangeAccent, fontWeight: 600 }}>
            egemenyucelen.me
          </div>
        </div>
      </div>
    </AbsoluteFill>
  );
};

// ============================================================================
// CARD 1: TOP 5-MAN LINEUP NET RATINGS (Possibilities Stream 01 Style)
// ============================================================================
export const Card1LineupsBenchmark: React.FC = () => {
  const lineups = [
    { team: 'Paris Basketball', names: 'Hayes · Herrera · Jantunen · Shorts · Ward', net: '+25.45', ortg: 132.8, drtg: 107.3, poss: 184, isLeader: true },
    { team: 'Fenerbahce Beko', names: 'Baldwin · Colson · Hayes-Davis · Melli · Hall', net: '+18.12', ortg: 124.5, drtg: 106.4, poss: 162, isLeader: false },
    { team: 'Panathinaikos AKTOR', names: 'Grant · Nunn · Grigonis · Mitoglou · Lessort', net: '+16.80', ortg: 126.2, drtg: 109.4, poss: 210, isLeader: false },
    { team: 'Real Madrid', names: 'Campazzo · Musa · Hezonja · Deck · Tavares', net: '+15.44', ortg: 123.1, drtg: 107.7, poss: 195, isLeader: false },
    { team: 'Olympiacos Piraeus', names: 'Walkup · Canaan · Papanikolaou · Peters · Fall', net: '+13.90', ortg: 121.6, drtg: 107.7, poss: 234, isLeader: false },
  ];

  return (
    <WebsiteCardFrame
      badgeText="EuroLeague 2024-25 • Lineup Intelligence"
      title="Top 5-man lineups by net rating efficiency"
      subtitle="Audited across 107,311 reconstructed possessions (min. 150 poss)"
      rightBadge={
        <span style={{ fontFamily: mono, fontSize: 12, color: tokens.textSecondary }}>
          Tool: <strong>el_get_lineup_stats</strong>
        </span>
      }
      footnote="Re-earned from raw play-by-play events. Dual-path validated against box score minute logs."
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        {lineups.map((item, idx) => (
          <div
            key={idx}
            style={{
              display: 'grid',
              gridTemplateColumns: '270px 1fr 110px',
              gap: 20,
              alignItems: 'center',
              background: item.isLeader ? tokens.orangeTint : tokens.bgPage,
              border: `1px solid ${item.isLeader ? tokens.orangeBorder : tokens.divider}`,
              borderRadius: 8,
              padding: '12px 18px',
            }}
          >
            {/* Team Info */}
            <div>
              <div style={{ fontSize: 16, fontWeight: 700, color: item.isLeader ? tokens.orangeAccent : tokens.textPrimary }}>
                {item.team}
              </div>
              <div style={{ fontFamily: mono, fontSize: 11, color: tokens.textSecondary, marginTop: 2, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                {item.names}
              </div>
            </div>

            {/* Metric Bars */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <div style={{ flex: 1, background: tokens.surface, height: 26, borderRadius: 4, border: `1px solid ${tokens.divider}`, overflow: 'hidden', position: 'relative', display: 'flex', alignItems: 'center', padding: '0 10px' }}>
                <div
                  style={{
                    position: 'absolute',
                    left: 0,
                    top: 0,
                    bottom: 0,
                    width: `${(parseFloat(item.net) / 28) * 100}%`,
                    background: item.isLeader ? tokens.orangeAccent : tokens.textSecondary,
                    opacity: item.isLeader ? 0.9 : 0.25,
                  }}
                />
                <span style={{ position: 'relative', zIndex: 2, fontFamily: mono, fontSize: 12, fontWeight: 600, color: tokens.textPrimary }}>
                  {item.ortg} ORtg &middot; {item.drtg} DRtg ({item.poss} poss)
                </span>
              </div>
            </div>

            {/* Net Rating */}
            <div style={{ textAlign: 'right' }}>
              <span
                style={{
                  fontSize: 22,
                  fontWeight: 700,
                  color: item.isLeader ? tokens.orangeAccent : tokens.textPrimary,
                  background: item.isLeader
                    ? 'linear-gradient(120deg, rgba(226, 84, 26, 0.16) 0%, rgba(245, 158, 11, 0.24) 100%)'
                    : 'transparent',
                  padding: '2px 6px',
                  borderRadius: 4,
                }}
              >
                {item.net}
              </span>
            </div>
          </div>
        ))}
      </div>
    </WebsiteCardFrame>
  );
};

// ============================================================================
// CARD 2: TJ SHORTS ON/OFF SPLIT & DEFENSIVE CLIFF (Act 1 / Hero Style)
// ============================================================================
export const Card2TJShortsBenchmark: React.FC = () => {
  return (
    <WebsiteCardFrame
      badgeText="EuroLeague 2024-25 • On/Off Impact Study"
      title="Paris Basketball efficiency with TJ Shorts on vs. off"
      subtitle="Sample: 34 games · 2,488 team possessions (P010461)"
      rightBadge={
        <span style={{ fontFamily: mono, fontSize: 12, color: tokens.textSecondary }}>
          Tool: <strong>el_get_player_on_off</strong>
        </span>
      }
      footnote="Calculated per 100 offensive possessions. Shows offensive parity and defensive dependency."
    >
      <div style={{ display: 'grid', gridTemplateColumns: '1.3fr 1px 1fr', gap: 36, alignItems: 'center' }}>
        {/* Left: On vs Off Bars */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
          {/* Offensive Rating */}
          <div style={{ background: tokens.bgPage, border: `1px solid ${tokens.divider}`, borderRadius: 8, padding: '16px 20px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: mono, fontSize: 12, color: tokens.textSecondary, marginBottom: 8 }}>
              <span style={{ fontWeight: 600, color: tokens.textPrimary }}>OFFENSIVE RATING (ORtg)</span>
              <span>Similar Scoring Ceiling</span>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <span style={{ fontFamily: mono, fontSize: 12, width: 34, color: tokens.orangeAccent, fontWeight: 700 }}>ON</span>
                <div style={{ flex: 1, background: tokens.surface, height: 26, borderRadius: 4, border: `1px solid ${tokens.orangeBorder}`, position: 'relative', overflow: 'hidden', display: 'flex', alignItems: 'center', paddingLeft: 10 }}>
                  <div style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: `${(116.14 / 140) * 100}%`, background: tokens.orangeAccent, opacity: 0.85 }} />
                  <span style={{ position: 'relative', zIndex: 2, fontFamily: mono, fontSize: 12, fontWeight: 600, color: '#FFF' }}>116.14 ORtg (1,667 poss)</span>
                </div>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <span style={{ fontFamily: mono, fontSize: 12, width: 34, color: tokens.textSecondary, fontWeight: 600 }}>OFF</span>
                <div style={{ flex: 1, background: tokens.surface, height: 26, borderRadius: 4, border: `1px solid ${tokens.divider}`, position: 'relative', overflow: 'hidden', display: 'flex', alignItems: 'center', paddingLeft: 10 }}>
                  <div style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: `${(117.05 / 140) * 100}%`, background: tokens.textPrimary, opacity: 0.7 }} />
                  <span style={{ position: 'relative', zIndex: 2, fontFamily: mono, fontSize: 12, fontWeight: 600, color: '#FFF' }}>117.05 ORtg (821 poss)</span>
                </div>
              </div>
            </div>
          </div>

          {/* Defensive Rating */}
          <div style={{ background: tokens.bgPage, border: `1px solid ${tokens.divider}`, borderRadius: 8, padding: '16px 20px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: mono, fontSize: 12, color: tokens.textSecondary, marginBottom: 8 }}>
              <span style={{ fontWeight: 600, color: tokens.textPrimary }}>DEFENSIVE RATING (DRtg)</span>
              <span style={{ color: tokens.orangeAccent, fontWeight: 600 }}>+17.46 Pts Conceded / 100</span>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <span style={{ fontFamily: mono, fontSize: 12, width: 34, color: tokens.orangeAccent, fontWeight: 700 }}>ON</span>
                <div style={{ flex: 1, background: tokens.surface, height: 26, borderRadius: 4, border: `1px solid ${tokens.orangeBorder}`, position: 'relative', overflow: 'hidden', display: 'flex', alignItems: 'center', paddingLeft: 10 }}>
                  <div style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: `${(111.04 / 140) * 100}%`, background: tokens.orangeAccent, opacity: 0.85 }} />
                  <span style={{ position: 'relative', zIndex: 2, fontFamily: mono, fontSize: 12, fontWeight: 600, color: '#FFF' }}>111.04 DRtg (Controlled)</span>
                </div>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <span style={{ fontFamily: mono, fontSize: 12, width: 34, color: tokens.textSecondary, fontWeight: 600 }}>OFF</span>
                <div style={{ flex: 1, background: tokens.surface, height: 26, borderRadius: 4, border: `1px solid ${tokens.divider}`, position: 'relative', overflow: 'hidden', display: 'flex', alignItems: 'center', paddingLeft: 10 }}>
                  <div style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: `${(128.50 / 140) * 100}%`, background: tokens.textPrimary, opacity: 0.7 }} />
                  <span style={{ position: 'relative', zIndex: 2, fontFamily: mono, fontSize: 12, fontWeight: 600, color: '#FFF' }}>128.50 DRtg (Defensive Cliff)</span>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div style={{ width: 1, height: '90%', background: tokens.divider }} />

        {/* Right: The Net Rating Differential Highlight */}
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', textAlign: 'center' }}>
          <div style={{ fontFamily: mono, fontSize: 13, textTransform: 'uppercase', letterSpacing: '0.12em', color: tokens.orangeAccent, fontWeight: 600 }}>
            Net Rating Swing
          </div>
          <div style={{ fontSize: 84, fontWeight: 700, letterSpacing: '-0.06em', color: tokens.textPrimary, lineHeight: 0.95, margin: '10px 0' }}>
            +16<span style={{ color: tokens.orangeAccent }}>.54</span>
          </div>
          <div style={{ fontSize: 16, color: tokens.textSecondary, maxWidth: 220, lineHeight: 1.35 }}>
            Total swing per 100 possessions when Shorts plays
          </div>
          <div style={{ marginTop: 18, background: tokens.orangeTint, border: `1px solid ${tokens.orangeBorder}`, padding: '8px 16px', borderRadius: 6, fontFamily: mono, fontSize: 13, color: tokens.orangeAccent, fontWeight: 600 }}>
            +5.09 ON vs. −11.45 OFF
          </div>
        </div>
      </div>
    </WebsiteCardFrame>
  );
};

// ============================================================================
// CARD 3: MECHANICAL INVARIANTS (Act 5 Trust Cards Style)
// ============================================================================
export const Card3TrustAuditSheet: React.FC = () => {
  const invariants = [
    { metric: 'Score Reconciliation', value: '100.0%', desc: '732 / 732 games with 0 pt variance', note: 'Official Box Parity' },
    { metric: 'Minute Match Accuracy', value: '99.54%', desc: 'Exact second-level player duration match', note: 'Stint Alignment' },
    { metric: 'Reconstructed Possessions', value: '107,311', desc: '5 deterministic ending conditions', note: 'Zero Box Formulas' },
    { metric: 'Dual-Path MCP Evals', value: '10 / 10', desc: 'Ground-truth SQL vs Live MCP parity', note: '100% Passing' },
  ];

  return (
    <WebsiteCardFrame
      badgeText="Warehouse Invariants • Ground Truth Audit"
      title="Mechanically verified against official box scores"
      subtitle="Automated assertions run on every commit across 732 public games"
      rightBadge={
        <div style={{ background: '#EDFDF2', border: '1px solid #B8F2C7', padding: '4px 12px', borderRadius: 4, fontFamily: mono, fontSize: 12, color: tokens.greenIndicator, fontWeight: 700, display: 'flex', alignItems: 'center', gap: 6 }}>
          <div style={{ width: 6, height: 6, borderRadius: '50%', background: tokens.greenIndicator }} />
          ALL INVARIANTS PASSED
        </div>
      }
      footnote="MIT Open Source. Dual-path evaluation guarantees analytical fidelity without hallucination."
    >
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 18 }}>
        {invariants.map((item, idx) => (
          <div
            key={idx}
            style={{
              background: tokens.bgPage,
              border: `1px solid ${tokens.divider}`,
              borderRadius: 10,
              padding: '24px 26px',
              display: 'flex',
              flexDirection: 'column',
              justifyContent: 'space-between',
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontSize: 16, fontWeight: 600, color: tokens.textPrimary }}>{item.metric}</span>
              <span style={{ fontFamily: mono, fontSize: 11, background: tokens.surface, border: `1px solid ${tokens.divider}`, padding: '2px 8px', borderRadius: 4, color: tokens.textSecondary, fontWeight: 600 }}>
                {item.note}
              </span>
            </div>
            <div style={{ fontSize: 48, fontWeight: 700, letterSpacing: '-0.045em', color: item.value.includes('%') ? tokens.orangeAccent : tokens.textPrimary, margin: '12px 0 6px' }}>
              {item.value}
            </div>
            <div style={{ fontFamily: mono, fontSize: 12, color: tokens.textSecondary }}>
              {item.desc}
            </div>
          </div>
        ))}
      </div>
    </WebsiteCardFrame>
  );
};

// ============================================================================
// CARD 4: CALLER-DEFINED CLUTCH EFFICIENCY (Possibilities Stream 02 Style)
// ============================================================================
export const Card4ClutchBenchmark: React.FC = () => {
  const clutchTeams = [
    { team: 'Fenerbahce Beko', clutch: 154.84, baseline: 119.21, diff: '+35.63', isLeader: true },
    { team: 'Real Madrid', clutch: 138.20, baseline: 122.80, diff: '+15.40', isLeader: false },
    { team: 'Panathinaikos AKTOR', clutch: 132.50, baseline: 121.40, diff: '+11.10', isLeader: false },
    { team: 'Olympiacos Piraeus', clutch: 124.60, baseline: 119.80, diff: '+4.80', isLeader: false },
  ];

  return (
    <WebsiteCardFrame
      badgeText="Dynamic Querying • Caller-Defined Clutch"
      title="Clutch offensive efficiency vs. regular season baseline"
      subtitle="Clutch Filter: Final 120s · Margin ≤ 3 at possession start · Min 20 poss"
      rightBadge={
        <span style={{ fontFamily: mono, fontSize: 12, color: tokens.textSecondary }}>
          Tool: <strong>el_get_possessions</strong>
        </span>
      }
      footnote="Dynamic calculation based on start-of-possession margin, without static hardcoded tables."
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        {clutchTeams.map((item, idx) => (
          <div
            key={idx}
            style={{
              display: 'grid',
              gridTemplateColumns: '220px 1fr 130px',
              gap: 20,
              alignItems: 'center',
              background: item.isLeader ? tokens.orangeTint : tokens.bgPage,
              border: `1px solid ${item.isLeader ? tokens.orangeBorder : tokens.divider}`,
              borderRadius: 8,
              padding: '14px 18px',
            }}
          >
            <div style={{ fontSize: 16, fontWeight: 700, color: item.isLeader ? tokens.orangeAccent : tokens.textPrimary }}>
              {item.team}
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <div style={{ width: `${(item.clutch / 170) * 100}%`, height: 22, background: item.isLeader ? tokens.orangeAccent : tokens.textPrimary, borderRadius: 3, display: 'flex', alignItems: 'center', paddingLeft: 8, color: '#FFF', fontFamily: mono, fontSize: 11, fontWeight: 600 }}>
                  {item.clutch} Clutch ORtg
                </div>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <div style={{ width: `${(item.baseline / 170) * 100}%`, height: 16, background: tokens.divider, borderRadius: 3, display: 'flex', alignItems: 'center', paddingLeft: 8, color: tokens.textSecondary, fontFamily: mono, fontSize: 10 }}>
                  {item.baseline} Baseline Avg
                </div>
              </div>
            </div>

            <div style={{ textAlign: 'right' }}>
              <div style={{ fontSize: 22, fontWeight: 700, color: item.isLeader ? tokens.orangeAccent : tokens.textPrimary }}>
                {item.diff}
              </div>
              <div style={{ fontFamily: mono, fontSize: 10, color: tokens.textSecondary, textTransform: 'uppercase' }}>
                Pts / 100 Leap
              </div>
            </div>
          </div>
        ))}
      </div>
    </WebsiteCardFrame>
  );
};
