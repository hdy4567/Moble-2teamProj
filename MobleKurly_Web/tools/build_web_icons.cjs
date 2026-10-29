// Build the public web icon family from the approved normal/admin v6 icons.
//
// The white MK artwork and alpha channel come from the approved normal icon.
// Only blue-dominant background pixels are shifted to the admin icon's blue
// family, keeping both products visually consistent without redrawing the logo.
//
// Usage (with sharp available through NODE_PATH):
//   node tools/build_web_icons.cjs

const fs = require('node:fs/promises');
const path = require('node:path');
const sharp = require('sharp');

const ROOT = path.resolve(__dirname, '..');
const IMAGES = path.join(ROOT, 'static', 'images');
const BRAND_OUTPUT = path.join(ROOT, '출력물', '브랜드');
const BASE = path.join(IMAGES, 'moble-kurly-shortcut-v6.png');
const ADMIN = path.join(IMAGES, 'moble-kurly-admin-shortcut-v6.png');
const FULL = path.join(IMAGES, 'moble-kurly-shortcut-v7.png');
const ICO = path.join(IMAGES, 'moble-kurly-shortcut-v7.ico');
const APPLE = path.join(IMAGES, 'moble-kurly-shortcut-v7-180.png');
const ICON_192 = path.join(IMAGES, 'moble-kurly-shortcut-v7-192.png');
const ICON_512 = path.join(IMAGES, 'moble-kurly-shortcut-v7-512.png');
const ICO_SIZES = [16, 24, 32, 48, 64, 128, 256];

function isBlue(r, g, b, a) {
  return a > 0 && b > 95 && b > r + 24 && b > g + 8 && r < 205;
}

function median(values) {
  const sorted = values.sort((a, b) => a - b);
  return sorted[Math.floor(sorted.length / 2)];
}

function backgroundMedian(data, width, height, excludeAdminBadge = false) {
  const channels = [[], [], []];
  for (let y = 0; y < height; y += 3) {
    for (let x = 0; x < width; x += 3) {
      if (excludeAdminBadge && x > width * 0.66 && y > height * 0.66) continue;
      const offset = (y * width + x) * 4;
      const r = data[offset];
      const g = data[offset + 1];
      const b = data[offset + 2];
      const a = data[offset + 3];
      if (a > 245 && isBlue(r, g, b, a)) {
        channels[0].push(r);
        channels[1].push(g);
        channels[2].push(b);
      }
    }
  }
  if (channels.some(channel => channel.length < 1000)) {
    throw new Error('Could not identify enough blue background pixels.');
  }
  return channels.map(median);
}

function clamp(value) {
  return Math.max(0, Math.min(255, Math.round(value)));
}

async function writeIco(source, destination) {
  const images = await Promise.all(ICO_SIZES.map(size => sharp(source)
    .resize(size, size, {
      fit: 'contain',
      kernel: sharp.kernel.lanczos3,
      background: { r: 0, g: 0, b: 0, alpha: 0 },
    })
    .png()
    .toBuffer()));
  const directory = Buffer.alloc(6 + 16 * ICO_SIZES.length);
  directory.writeUInt16LE(1, 2);
  directory.writeUInt16LE(ICO_SIZES.length, 4);
  let offset = directory.length;
  images.forEach((png, index) => {
    const entry = 6 + 16 * index;
    const size = ICO_SIZES[index];
    directory[entry] = size === 256 ? 0 : size;
    directory[entry + 1] = directory[entry];
    directory.writeUInt16LE(1, entry + 4);
    directory.writeUInt16LE(32, entry + 6);
    directory.writeUInt32LE(png.length, entry + 8);
    directory.writeUInt32LE(offset, entry + 12);
    offset += png.length;
  });
  await fs.writeFile(destination, Buffer.concat([directory, ...images]));
}

async function build() {
  const base = await sharp(BASE).ensureAlpha().raw().toBuffer({ resolveWithObject: true });
  const admin = await sharp(ADMIN).ensureAlpha().raw().toBuffer({ resolveWithObject: true });
  if (base.info.width !== admin.info.width || base.info.height !== admin.info.height
      || base.info.channels !== 4 || admin.info.channels !== 4) {
    throw new Error('Approved icon dimensions or channels do not match.');
  }

  const sourceMedian = backgroundMedian(base.data, base.info.width, base.info.height);
  const targetMedian = backgroundMedian(
    admin.data, admin.info.width, admin.info.height, true,
  );
  const delta = targetMedian.map((value, index) => value - sourceMedian[index]);
  const output = Buffer.from(base.data);

  for (let offset = 0; offset < output.length; offset += 4) {
    const r = output[offset];
    const g = output[offset + 1];
    const b = output[offset + 2];
    const a = output[offset + 3];
    if (!isBlue(r, g, b, a)) continue;
    output[offset] = clamp(r + delta[0]);
    output[offset + 1] = clamp(g + delta[1]);
    output[offset + 2] = clamp(b + delta[2]);
  }

  await sharp(output, {
    raw: { width: base.info.width, height: base.info.height, channels: 4 },
  }).png({ compressionLevel: 9 }).toFile(FULL);
  await Promise.all([
    sharp(FULL).resize(180, 180, { kernel: sharp.kernel.lanczos3 }).png().toFile(APPLE),
    sharp(FULL).resize(192, 192, { kernel: sharp.kernel.lanczos3 }).png().toFile(ICON_192),
    sharp(FULL).resize(512, 512, { kernel: sharp.kernel.lanczos3 }).png().toFile(ICON_512),
  ]);
  await writeIco(FULL, ICO);

  await fs.mkdir(BRAND_OUTPUT, { recursive: true });
  await Promise.all([
    fs.copyFile(FULL, path.join(BRAND_OUTPUT, '웹아이콘.png')),
    fs.copyFile(ICO, path.join(BRAND_OUTPUT, '웹아이콘.ico')),
  ]);

  const result = {
    sourceMedian: `#${sourceMedian.map(value => value.toString(16).padStart(2, '0')).join('')}`,
    targetMedian: `#${targetMedian.map(value => value.toString(16).padStart(2, '0')).join('')}`,
    delta,
    outputs: [FULL, ICO, APPLE, ICON_192, ICON_512],
  };
  process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
}

build().catch(error => {
  console.error(error.stack || error.message);
  process.exitCode = 1;
});
