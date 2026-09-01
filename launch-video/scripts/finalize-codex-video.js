const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');

const root = path.join(__dirname, '..');
const ffmpeg = path.join(
  root,
  'node_modules',
  '@remotion',
  'compositor-win32-x64-msvc',
  'ffmpeg.exe'
);
const output = path.join(root, 'output', 'euroleague-launch-codex.mp4');
const trimmed = path.join(root, 'output', 'euroleague-launch-codex.exact.mp4');

const result = spawnSync(
  ffmpeg,
  [
    '-hide_banner',
    '-loglevel',
    'error',
    '-i',
    output,
    '-t',
    '29.99',
    '-map',
    '0:v:0',
    '-map',
    '0:a:0',
    '-c',
    'copy',
    '-movflags',
    '+faststart',
    '-y',
    trimmed,
  ],
  { stdio: 'inherit' }
);

if (result.status !== 0) {
  process.exit(result.status ?? 1);
}

fs.rmSync(output);
fs.renameSync(trimmed, output);
console.log('Finalized exact 30.000-second MP4 container.');
