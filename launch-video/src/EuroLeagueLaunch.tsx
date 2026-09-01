import React from 'react';
import {
  AbsoluteFill,
  Audio,
  Sequence,
  interpolate,
  staticFile,
  useCurrentFrame,
} from 'remotion';
import { CourtBackground } from './design/CourtBackground';
import { Scene1Hook } from './scenes/Scene1Hook';
import { Scene2Product } from './scenes/Scene2Product';
import { Scene3ChatConversation } from './scenes/Scene3ChatConversation';
import { Scene5Proof } from './scenes/Scene5Proof';
import { Scene6Close } from './scenes/Scene6Close';

export const EuroLeagueLaunch: React.FC = () => {
  const frame = useCurrentFrame();

  // Master volume control with smooth fade out near the end
  const musicVolume = interpolate(frame, [0, 15, 870, 900], [0, 0.82, 0.82, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  return (
    <AbsoluteFill style={{ backgroundColor: '#F8FAFC' }}>
      {/* 1. Global Light Basketball Court Canvas */}
      <CourtBackground opacity={0.8} />

      {/* 2. Audio Bed (120 BPM Minimal Electronic Music) */}
      <Audio src={staticFile('audio/music-bed.wav')} volume={musicVolume} />

      {/* 3. Basketball & Interactive SFX Tracks */}
      {/* Scene 1 Intro Clicks */}
      <Sequence from={8} durationInFrames={15}>
        <Audio src={staticFile('audio/tick.wav')} volume={0.35} />
      </Sequence>
      <Sequence from={48} durationInFrames={15}>
        <Audio src={staticFile('audio/tick.wav')} volume={0.4} />
      </Sequence>

      {/* Scene 2 Transition Whoosh */}
      <Sequence from={120} durationInFrames={20}>
        <Audio src={staticFile('audio/transition.wav')} volume={0.3} />
      </Sequence>

      {/* Scene 3: User Typing Sound Burst */}
      <Sequence from={250} durationInFrames={65}>
        <Audio src={staticFile('audio/typing.wav')} volume={0.45} />
      </Sequence>

      {/* Scene 3: Assistant Thinking Hum/Pulse */}
      <Sequence from={310} durationInFrames={35}>
        <Audio src={staticFile('audio/thinking.wav')} volume={0.4} />
      </Sequence>

      {/* Scene 3: Hero Answer Reveal (Basketball Swish & Impact) */}
      <Sequence from={348} durationInFrames={25}>
        <Audio src={staticFile('audio/swish.wav')} volume={0.6} />
      </Sequence>
      <Sequence from={350} durationInFrames={30}>
        <Audio src={staticFile('audio/impact.wav')} volume={0.55} />
      </Sequence>

      {/* Scene 4: Proof Transition & Stat Drops */}
      <Sequence from={540} durationInFrames={20}>
        <Audio src={staticFile('audio/transition.wav')} volume={0.35} />
      </Sequence>
      <Sequence from={546} durationInFrames={30}>
        <Audio src={staticFile('audio/impact.wav')} volume={0.65} />
      </Sequence>
      <Sequence from={585} durationInFrames={30}>
        <Audio src={staticFile('audio/impact.wav')} volume={0.65} />
      </Sequence>
      <Sequence from={625} durationInFrames={30}>
        <Audio src={staticFile('audio/impact.wav')} volume={0.7} />
      </Sequence>

      {/* Scene 5: Outro Transition */}
      <Sequence from={720} durationInFrames={25}>
        <Audio src={staticFile('audio/transition.wav')} volume={0.35} />
      </Sequence>

      {/* 4. Visual Scene Sequences (900 Frames / 30.00s Total) */}
      {/* Scene 1: Hook (0:00 - 0:04, 120 frames) */}
      <Sequence from={0} durationInFrames={120}>
        <Scene1Hook />
      </Sequence>

      {/* Scene 2: Product Brand Reveal (0:04 - 0:08, 120 frames) */}
      <Sequence from={120} durationInFrames={120}>
        <Scene2Product />
      </Sequence>

      {/* Scene 3: AI Conversation & Hero On/Off Result (0:08 - 0:18, 300 frames) */}
      <Sequence from={240} durationInFrames={300}>
        <Scene3ChatConversation />
      </Sequence>

      {/* Scene 4: Proof & Verified Invariants (0:18 - 0:24, 180 frames) */}
      <Sequence from={540} durationInFrames={180}>
        <Scene5Proof />
      </Sequence>

      {/* Scene 5: Clean Close (0:24 - 0:30, 180 frames) */}
      <Sequence from={720} durationInFrames={180}>
        <Scene6Close />
      </Sequence>
    </AbsoluteFill>
  );
};
