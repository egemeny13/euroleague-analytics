const fs = require('fs');
const path = require('path');

// Audio parameters
const SAMPLE_RATE = 44100;
const DURATION = 30.5; // 30.5 seconds
const TOTAL_SAMPLES = Math.floor(SAMPLE_RATE * DURATION);
const BPM = 120;
const BEAT_SEC = 60 / BPM; // 0.5s per beat

// Helper to create WAV buffer
function createWavBuffer(leftChannel, rightChannel, sampleRate = SAMPLE_RATE) {
  const numSamples = leftChannel.length;
  const numChannels = rightChannel ? 2 : 1;
  const byteRate = sampleRate * numChannels * 2;
  const blockAlign = numChannels * 2;
  const buffer = Buffer.alloc(44 + numSamples * blockAlign);

  // RIFF header
  buffer.write('RIFF', 0);
  buffer.writeUInt32LE(36 + numSamples * blockAlign, 4);
  buffer.write('WAVE', 8);

  // fmt subchunk
  buffer.write('fmt ', 12);
  buffer.writeUInt32LE(16, 16);
  buffer.writeUInt16LE(1, 20); // PCM format
  buffer.writeUInt16LE(numChannels, 22);
  buffer.writeUInt32LE(sampleRate, 24);
  buffer.writeUInt32LE(byteRate, 28);
  buffer.writeUInt16LE(blockAlign, 32);
  buffer.writeUInt16LE(16, 34); // 16-bit

  // data subchunk
  buffer.write('data', 36);
  buffer.writeUInt32LE(numSamples * blockAlign, 40);

  let offset = 44;
  for (let i = 0; i < numSamples; i++) {
    let sL = Math.max(-1, Math.min(1, leftChannel[i]));
    let valL = sL < 0 ? sL * 32768 : sL * 32767;
    buffer.writeInt16LE(Math.floor(valL), offset);
    offset += 2;

    if (numChannels === 2) {
      let sR = Math.max(-1, Math.min(1, rightChannel[i]));
      let valR = sR < 0 ? sR * 32768 : sR * 32767;
      buffer.writeInt16LE(Math.floor(valR), offset);
      offset += 2;
    }
  }

  return buffer;
}

// Generate Minimal Electronic Music Bed (120 BPM, Clean / Rhythmic / Modern)
function generateMusicBed() {
  const left = new Float32Array(TOTAL_SAMPLES);
  const right = new Float32Array(TOTAL_SAMPLES);

  const numBeats = Math.floor(DURATION / BEAT_SEC);
  const rootFreq = 73.42; // D2

  for (let b = 0; b < numBeats; b++) {
    const beatTime = b * BEAT_SEC;
    const startSample = Math.floor(beatTime * SAMPLE_RATE);

    // KICK DRUM: beats 8 to 52
    if (b >= 8 && b < 52) {
      const isProofDrop = (b >= 36 && b < 48);
      const isAccent = (b === 8 || b === 16 || b === 24 || b === 36 || b === 40 || b === 44);
      
      const kickLen = Math.floor(SAMPLE_RATE * 0.32);
      for (let i = 0; i < kickLen && (startSample + i) < TOTAL_SAMPLES; i++) {
        const t = i / SAMPLE_RATE;
        const env = Math.exp(-t * (isProofDrop ? 13 : 17));
        const freq = 125 * Math.exp(-t * 30) + 40;
        const phase = 2 * Math.PI * freq * t;
        const sample = Math.sin(phase) * env * (isAccent ? 0.7 : 0.55);
        left[startSample + i] += sample;
        right[startSample + i] += sample;
      }
    }

    // TECH HI-HATS / SHAKERS: beats 16 to 50
    if (b >= 16 && b < 50) {
      const hatStart = startSample + Math.floor(0.25 * SAMPLE_RATE);
      const hatLen = Math.floor(SAMPLE_RATE * 0.045);
      for (let i = 0; i < hatLen && (hatStart + i) < TOTAL_SAMPLES; i++) {
        const t = i / SAMPLE_RATE;
        const env = Math.exp(-t * 90);
        const noise = (Math.random() * 2 - 1) * env * 0.14;
        left[hatStart + i] += noise * 0.8;
        right[hatStart + i] += noise * 1.0;
      }
    }
  }

  // CONTINUOUS BASSLINE & HARMONIC BED
  for (let s = 0; s < TOTAL_SAMPLES; s++) {
    const t = s / SAMPLE_RATE;
    const currentBeat = t / BEAT_SEC;

    let masterEnv = 1.0;
    if (t < 0.2) masterEnv = t / 0.2;
    if (t > 29.0) masterEnv = Math.max(0, 1 - (t - 29.0) / 1.5);

    // Warm sub tone
    let subFreq = rootFreq;
    if (t >= 8 && t < 18) subFreq = (Math.floor(currentBeat / 4) % 2 === 0) ? rootFreq : rootFreq * 1.189;
    if (t >= 18 && t < 24) subFreq = rootFreq;

    const subOsc = Math.sin(2 * Math.PI * subFreq * t);
    const subLevel = (t < 4 ? 0.22 : (t > 25 ? 0.18 : 0.3));
    left[s] += subOsc * subLevel * masterEnv;
    right[s] += subOsc * subLevel * masterEnv;

    // Minimal rhythmic pluck
    if (t >= 4 && t < 25) {
      const sixteenth = Math.floor(t / (BEAT_SEC / 4));
      const arpNotes = [146.83, 174.61, 220.00, 261.63]; // D3, F3, A3, C4
      const noteFreq = arpNotes[sixteenth % 4];
      const notePhase = (t % (BEAT_SEC / 4)) / (BEAT_SEC / 4);
      const noteEnv = Math.exp(-notePhase * 14);
      
      const sine = Math.sin(2 * Math.PI * noteFreq * t);
      const pluck = sine * noteEnv * 0.16 * masterEnv;
      
      left[s] += pluck * 0.9;
      right[s] += pluck * 1.1;
    }

    // Airy clean pad
    const padFreq1 = 293.66; // D4
    const padFreq2 = 440.00; // A4
    const pad = (
      Math.sin(2 * Math.PI * padFreq1 * t) * 0.5 +
      Math.sin(2 * Math.PI * padFreq2 * t) * 0.5
    ) * 0.045 * masterEnv;

    left[s] += pad;
    right[s] += pad;
  }

  // Normalization
  let maxPeak = 0;
  for (let i = 0; i < TOTAL_SAMPLES; i++) {
    maxPeak = Math.max(maxPeak, Math.abs(left[i]), Math.abs(right[i]));
  }
  const normFactor = 0.85 / (maxPeak || 1);
  for (let i = 0; i < TOTAL_SAMPLES; i++) {
    left[i] = Math.tanh(left[i] * normFactor);
    right[i] = Math.tanh(right[i] * normFactor);
  }

  return createWavBuffer(left, right);
}

// SFX 1: Realistic Keyboard Typing Burst (for AI query typing)
function generateTypingSFX() {
  const duration = 2.2; // 2.2 seconds burst of natural key clicks
  const samples = Math.floor(SAMPLE_RATE * duration);
  const left = new Float32Array(samples);
  const right = new Float32Array(samples);

  // Random key stroke times
  let tKey = 0.04;
  while (tKey < duration - 0.05) {
    const keySample = Math.floor(tKey * SAMPLE_RATE);
    const keyLen = Math.floor(SAMPLE_RATE * 0.035);
    const freq = 1800 + Math.random() * 1200;
    const pan = 0.4 + Math.random() * 0.2;

    for (let i = 0; i < keyLen && (keySample + i) < samples; i++) {
      const t = i / SAMPLE_RATE;
      const env = Math.exp(-t * 160);
      const click = (Math.sin(2 * Math.PI * freq * t) * 0.35 + (Math.random() * 2 - 1) * 0.65) * env * 0.35;
      left[keySample + i] += click * (1 - pan);
      right[keySample + i] += click * pan;
    }
    tKey += 0.055 + Math.random() * 0.045; // ~15 keys per second typing speed
  }

  return createWavBuffer(left, right);
}

// SFX 2: Assistant "Thinking" / Computation Pulse
function generateThinkingSFX() {
  const duration = 1.0;
  const samples = Math.floor(SAMPLE_RATE * duration);
  const left = new Float32Array(samples);
  const right = new Float32Array(samples);

  for (let i = 0; i < samples; i++) {
    const t = i / SAMPLE_RATE;
    const env = Math.sin((t / duration) * Math.PI);
    const lfo = Math.sin(2 * Math.PI * 6 * t); // 6Hz thinking pulse
    const tone = Math.sin(2 * Math.PI * (520 + lfo * 40) * t) * 0.15 * env;
    const tone2 = Math.sin(2 * Math.PI * (780 + lfo * 60) * t) * 0.1 * env;
    left[i] = tone + tone2;
    right[i] = tone * 0.9 + tone2 * 1.1;
  }

  return createWavBuffer(left, right);
}

// SFX 3: Restrained Basketball Net Swish (Clean white noise whoosh with high resonance)
function generateSwishSFX() {
  const duration = 0.45;
  const samples = Math.floor(SAMPLE_RATE * duration);
  const left = new Float32Array(samples);
  const right = new Float32Array(samples);

  for (let i = 0; i < samples; i++) {
    const t = i / SAMPLE_RATE;
    // Fast attack, smooth decay envelope
    const env = Math.pow(Math.sin((t / duration) * Math.PI), 1.6);
    const noise = (Math.random() * 2 - 1);
    // Bandpass-like filtered high swoosh
    const swoosh = noise * env * 0.4;
    left[i] = swoosh * 0.85;
    right[i] = swoosh * 1.15;
  }

  return createWavBuffer(left, right);
}

// SFX 4: Sub Stat Impact / Hardwood Thud
function generateImpactSFX() {
  const duration = 0.7;
  const samples = Math.floor(SAMPLE_RATE * duration);
  const left = new Float32Array(samples);
  const right = new Float32Array(samples);

  for (let i = 0; i < samples; i++) {
    const t = i / SAMPLE_RATE;
    const env = Math.exp(-t * 6.5);
    const freq = 120 * Math.exp(-t * 22) + 38;
    const sub = Math.sin(2 * Math.PI * freq * t) * 0.75 * env;
    const click = (Math.random() * 2 - 1) * Math.exp(-t * 100) * 0.25;
    left[i] = Math.tanh(sub + click);
    right[i] = Math.tanh(sub + click);
  }

  return createWavBuffer(left, right);
}

// SFX 5: Clean UI Tick
function generateTickSFX() {
  const samples = Math.floor(SAMPLE_RATE * 0.05);
  const left = new Float32Array(samples);
  for (let i = 0; i < samples; i++) {
    const t = i / SAMPLE_RATE;
    const env = Math.exp(-t * 150);
    const click = (Math.sin(2 * Math.PI * 2600 * t) * 0.4 + (Math.random() * 2 - 1) * 0.6) * env * 0.35;
    left[i] = click;
  }
  return createWavBuffer(left, left);
}

// SFX 6: Transition Whoosh
function generateTransitionSFX() {
  const duration = 0.45;
  const samples = Math.floor(SAMPLE_RATE * duration);
  const left = new Float32Array(samples);
  const right = new Float32Array(samples);

  for (let i = 0; i < samples; i++) {
    const t = i / SAMPLE_RATE;
    const env = Math.sin((t / duration) * Math.PI);
    const noise = (Math.random() * 2 - 1) * env * 0.22;
    const tone = Math.sin(2 * Math.PI * (160 + t * 450) * t) * env * 0.18;
    left[i] = noise * 0.7 + tone;
    right[i] = noise * 0.9 + tone;
  }

  return createWavBuffer(left, right);
}

// Write files
const audioDir = path.join(__dirname, '..', 'public', 'audio');
fs.mkdirSync(audioDir, { recursive: true });

fs.writeFileSync(path.join(audioDir, 'music-bed.wav'), generateMusicBed());
fs.writeFileSync(path.join(audioDir, 'typing.wav'), generateTypingSFX());
fs.writeFileSync(path.join(audioDir, 'thinking.wav'), generateThinkingSFX());
fs.writeFileSync(path.join(audioDir, 'swish.wav'), generateSwishSFX());
fs.writeFileSync(path.join(audioDir, 'impact.wav'), generateImpactSFX());
fs.writeFileSync(path.join(audioDir, 'tick.wav'), generateTickSFX());
fs.writeFileSync(path.join(audioDir, 'transition.wav'), generateTransitionSFX());

console.log('V2 audio assets generated successfully in:', audioDir);
