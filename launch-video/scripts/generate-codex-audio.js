const fs = require('fs');
const path = require('path');

const SAMPLE_RATE = 48000;

const seededRandom = (seed) => {
  let value = seed >>> 0;
  return () => {
    value += 0x6d2b79f5;
    let next = value;
    next = Math.imul(next ^ (next >>> 15), next | 1);
    next ^= next + Math.imul(next ^ (next >>> 7), next | 61);
    return ((next ^ (next >>> 14)) >>> 0) / 4294967296;
  };
};

const random = seededRandom(20240901);

const wav = (left, right) => {
  const samples = left.length;
  const buffer = Buffer.alloc(44 + samples * 4);
  buffer.write('RIFF', 0);
  buffer.writeUInt32LE(36 + samples * 4, 4);
  buffer.write('WAVE', 8);
  buffer.write('fmt ', 12);
  buffer.writeUInt32LE(16, 16);
  buffer.writeUInt16LE(1, 20);
  buffer.writeUInt16LE(2, 22);
  buffer.writeUInt32LE(SAMPLE_RATE, 24);
  buffer.writeUInt32LE(SAMPLE_RATE * 4, 28);
  buffer.writeUInt16LE(4, 32);
  buffer.writeUInt16LE(16, 34);
  buffer.write('data', 36);
  buffer.writeUInt32LE(samples * 4, 40);

  let offset = 44;
  for (let index = 0; index < samples; index += 1) {
    const l = Math.max(-1, Math.min(1, left[index]));
    const r = Math.max(-1, Math.min(1, right[index]));
    buffer.writeInt16LE(Math.round(l * (l < 0 ? 32768 : 32767)), offset);
    buffer.writeInt16LE(Math.round(r * (r < 0 ? 32768 : 32767)), offset + 2);
    offset += 4;
  }
  return buffer;
};

const stereo = (seconds) => {
  const length = Math.ceil(seconds * SAMPLE_RATE);
  return [new Float32Array(length), new Float32Array(length)];
};

const addTone = (channels, start, duration, frequency, gain, decay = 6, pan = 0) => {
  const startSample = Math.floor(start * SAMPLE_RATE);
  const length = Math.floor(duration * SAMPLE_RATE);
  for (let index = 0; index < length; index += 1) {
    const target = startSample + index;
    if (target >= channels[0].length) break;
    const time = index / SAMPLE_RATE;
    const envelope = Math.exp(-time * decay);
    const sample = Math.sin(Math.PI * 2 * frequency * time) * envelope * gain;
    channels[0][target] += sample * (1 - Math.max(0, pan));
    channels[1][target] += sample * (1 + Math.min(0, pan));
  }
};

const addNoise = (channels, start, duration, gain, decay = 18, pan = 0) => {
  const startSample = Math.floor(start * SAMPLE_RATE);
  const length = Math.floor(duration * SAMPLE_RATE);
  let previous = 0;
  for (let index = 0; index < length; index += 1) {
    const target = startSample + index;
    if (target >= channels[0].length) break;
    const time = index / SAMPLE_RATE;
    const white = random() * 2 - 1;
    const high = white - previous * 0.72;
    previous = white;
    const sample = high * Math.exp(-time * decay) * gain;
    channels[0][target] += sample * (1 - Math.max(0, pan));
    channels[1][target] += sample * (1 + Math.min(0, pan));
  }
};

const normalize = (channels, peak = 0.86) => {
  let maximum = 0;
  for (let index = 0; index < channels[0].length; index += 1) {
    maximum = Math.max(maximum, Math.abs(channels[0][index]), Math.abs(channels[1][index]));
  }
  const scale = maximum === 0 ? 1 : peak / maximum;
  for (let index = 0; index < channels[0].length; index += 1) {
    channels[0][index] = Math.tanh(channels[0][index] * scale);
    channels[1][index] = Math.tanh(channels[1][index] * scale);
  }
  return channels;
};

const music = () => {
  const channels = stereo(30.2);
  const beat = 0.6;
  const roots = [55, 55, 65.41, 49, 55];

  for (let sample = 0; sample < channels[0].length; sample += 1) {
    const time = sample / SAMPLE_RATE;
    const section = Math.min(roots.length - 1, Math.floor(time / 6));
    const root = roots[section];
    const fadeIn = Math.min(1, time / 1.4);
    const fadeOut = time > 28 ? Math.max(0, (30.2 - time) / 2.2) : 1;
    const pulse = 0.72 + 0.28 * Math.sin(Math.PI * 2 * time / 2.4);
    const sub = Math.sin(Math.PI * 2 * root * time) * 0.065;
    const fifth = Math.sin(Math.PI * 2 * root * 1.5 * time + 0.4) * 0.028;
    const air = Math.sin(Math.PI * 2 * root * 4 * time) * 0.009 * pulse;
    channels[0][sample] += (sub + fifth + air) * fadeIn * fadeOut;
    channels[1][sample] += (sub + fifth * 0.94 - air) * fadeIn * fadeOut;
  }

  for (let time = 3.6, beatIndex = 0; time < 27; time += beat, beatIndex += 1) {
    if (beatIndex % 4 === 0 || beatIndex % 4 === 2) {
      addTone(channels, time, 0.34, 52, beatIndex % 8 === 0 ? 0.34 : 0.27, 10);
      addNoise(channels, time, 0.026, 0.06, 130);
    }
    if (beatIndex % 4 === 1 || beatIndex % 4 === 3) {
      addTone(channels, time, 0.16, 184, 0.07, 23, beatIndex % 4 === 1 ? -0.1 : 0.1);
      addNoise(channels, time, 0.065, 0.035, 70, beatIndex % 4 === 1 ? -0.16 : 0.16);
    }
    if (time > 6 && beatIndex % 2 === 0) {
      addNoise(channels, time + beat / 2, 0.04, 0.025, 105, beatIndex % 4 === 0 ? 0.22 : -0.22);
    }
  }

  [3.1, 10.05, 13.5, 16.9, 21.1, 26.45].forEach((time, index) => {
    addTone(channels, time, 0.55, index === 3 ? 82.41 : 73.42, 0.13, 7);
  });

  return wav(...normalize(channels, 0.76));
};

const typing = () => {
  const channels = stereo(4.8);
  let time = 0.05;
  let index = 0;
  while (time < 4.66) {
    const pause = index % 14 === 10 ? 0.13 : index % 22 === 0 ? 0.09 : 0;
    addNoise(channels, time, 0.032, 0.18, 135, (random() - 0.5) * 0.34);
    addTone(channels, time, 0.05, 1250 + random() * 650, 0.045, 92, (random() - 0.5) * 0.34);
    time += 0.042 + random() * 0.023 + pause;
    index += 1;
  }
  return wav(...normalize(channels, 0.55));
};

const enter = () => {
  const channels = stereo(0.42);
  addNoise(channels, 0.01, 0.05, 0.24, 95);
  addTone(channels, 0.015, 0.34, 96, 0.36, 13);
  addTone(channels, 0.03, 0.2, 192, 0.08, 18);
  return wav(...normalize(channels, 0.72));
};

const tool = () => {
  const channels = stereo(0.55);
  addTone(channels, 0.01, 0.22, 660, 0.18, 13, -0.15);
  addTone(channels, 0.11, 0.34, 990, 0.16, 10, 0.15);
  addNoise(channels, 0.1, 0.028, 0.08, 145);
  return wav(...normalize(channels, 0.58));
};

const swish = () => {
  const channels = stereo(0.72);
  const length = channels[0].length;
  let previous = 0;
  for (let index = 0; index < length; index += 1) {
    const time = index / SAMPLE_RATE;
    const position = time / 0.72;
    const envelope = Math.pow(Math.sin(Math.PI * position), 2.3);
    const white = random() * 2 - 1;
    const filtered = white - previous * 0.86;
    previous = white;
    channels[0][index] = filtered * envelope * 0.18 * (1 - position * 0.18);
    channels[1][index] = filtered * envelope * 0.21 * (0.82 + position * 0.18);
  }
  return wav(...normalize(channels, 0.42));
};

const air = () => {
  const channels = stereo(0.9);
  const length = channels[0].length;
  let previous = 0;
  for (let index = 0; index < length; index += 1) {
    const position = index / length;
    const white = random() * 2 - 1;
    const filtered = previous * 0.88 + white * 0.12;
    previous = filtered;
    const envelope = Math.pow(Math.sin(Math.PI * position), 1.4);
    channels[0][index] = filtered * envelope * 0.16 * (1 - position * 0.35);
    channels[1][index] = filtered * envelope * 0.16 * (0.65 + position * 0.35);
  }
  return wav(...normalize(channels, 0.4));
};

const audioDirectory = path.join(__dirname, '..', 'public', 'audio');
fs.mkdirSync(audioDirectory, { recursive: true });

const files = {
  'codex-music.wav': music(),
  'codex-typing.wav': typing(),
  'codex-enter.wav': enter(),
  'codex-tool.wav': tool(),
  'codex-swish.wav': swish(),
  'codex-air.wav': air(),
};

for (const [name, contents] of Object.entries(files)) {
  fs.writeFileSync(path.join(audioDirectory, name), contents);
}

console.log(`Generated ${Object.keys(files).length} original Codex audio assets.`);
