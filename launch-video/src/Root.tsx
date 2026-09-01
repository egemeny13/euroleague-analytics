import React from 'react';
import { Composition } from 'remotion';
import { CodexLaunch } from './CodexLaunch';
import { EuroLeagueLaunch } from './EuroLeagueLaunch';
import { ClipTJShorts, ClipVerification } from './microClips';
import {
  Card1LineupsBenchmark,
  Card2TJShortsBenchmark,
  Card3TrustAuditSheet,
  Card4ClutchBenchmark,
} from './statCards';

export const Root: React.FC = () => {
  return (
    <>
      <Composition
        id="EuroLeagueLaunch"
        component={EuroLeagueLaunch}
        durationInFrames={900}
        fps={30}
        width={1920}
        height={1080}
      />
      <Composition
        id="EuroLeagueLaunchCodex"
        component={CodexLaunch}
        durationInFrames={900}
        fps={30}
        width={1920}
        height={1080}
      />
      <Composition
        id="ClipTJShorts"
        component={ClipTJShorts}
        durationInFrames={300}
        fps={30}
        width={1920}
        height={1080}
      />
      <Composition
        id="ClipVerification"
        component={ClipVerification}
        durationInFrames={240}
        fps={30}
        width={1920}
        height={1080}
      />
      <Composition
        id="Card1LineupsBenchmark"
        component={Card1LineupsBenchmark}
        durationInFrames={1}
        fps={30}
        width={1200}
        height={1000}
      />
      <Composition
        id="Card2TJShortsBenchmark"
        component={Card2TJShortsBenchmark}
        durationInFrames={1}
        fps={30}
        width={1200}
        height={1000}
      />
      <Composition
        id="Card3TrustAuditSheet"
        component={Card3TrustAuditSheet}
        durationInFrames={1}
        fps={30}
        width={1200}
        height={1000}
      />
      <Composition
        id="Card4ClutchBenchmark"
        component={Card4ClutchBenchmark}
        durationInFrames={1}
        fps={30}
        width={1200}
        height={1000}
      />
    </>
  );
};
