const fs = require('fs');
const path = require('path');

const root = path.join(__dirname, '..');

const read = (relativePath) =>
  fs.readFileSync(path.join(root, relativePath), 'utf8');

const requireText = (source, value, label) => {
  if (!source.includes(value)) {
    throw new Error(`${label}: missing ${JSON.stringify(value)}`);
  }
};

const rootSource = read('src/Root.tsx');
const filmSource = read('src/CodexLaunch.tsx');
const packageJson = JSON.parse(read('package.json'));

requireText(rootSource, 'id="EuroLeagueLaunchCodex"', 'composition');
requireText(rootSource, 'durationInFrames={900}', 'duration');
requireText(rootSource, 'width={1920}', 'width');
requireText(rootSource, 'height={1080}', 'height');
requireText(rootSource, 'fps={30}', 'frame rate');

for (const claim of [
  'el_get_player_on_off',
  '+5.09',
  '-11.45',
  '+16.54',
  '1,667',
  '821',
  '107,311',
  '732',
  '100%',
  'github.com/egemeny13/euroleague-analytics',
]) {
  requireText(filmSource, claim, 'verified film copy');
}

for (const asset of [
  'public/audio/codex-music.wav',
  'public/audio/codex-typing.wav',
  'public/audio/codex-enter.wav',
  'public/audio/codex-tool.wav',
  'public/audio/codex-swish.wav',
  'public/audio/codex-air.wav',
]) {
  if (!fs.existsSync(path.join(root, asset))) {
    throw new Error(`audio asset missing: ${asset}`);
  }
}

if (
  packageJson.scripts['build:codex'] !==
  'remotion render src/index.ts EuroLeagueLaunchCodex output/euroleague-launch-codex.mp4 --codec=h264 && node scripts/finalize-codex-video.js'
) {
  throw new Error('build:codex must render and exact-trim the independent H.264 deliverable');
}

console.log('Codex launch-video contract passed.');
