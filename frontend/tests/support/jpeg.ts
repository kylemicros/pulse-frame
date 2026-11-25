const START_OF_FRAME = new Set([0xc0, 0xc1, 0xc2, 0xc3, 0xc5, 0xc6, 0xc7, 0xc9, 0xca, 0xcb, 0xcd, 0xce, 0xcf]);

const DEFINE_QUANTIZATION = 0xdb;
const START_OF_SCAN = 0xda;

const STANDARD_LUMINANCE = [
  16, 11, 10, 16, 24, 40, 51, 61, 12, 12, 14, 19, 26, 58, 60, 55, 14, 13, 16, 24, 40, 57, 69, 56, 14, 17, 22, 29, 51, 87,
  80, 62, 18, 22, 37, 56, 68, 109, 103, 77, 24, 35, 55, 64, 81, 104, 113, 92, 49, 64, 78, 87, 103, 121, 120, 101, 72, 92,
  95, 98, 112, 100, 103, 99,
];

const ZIGZAG = [
  0, 1, 8, 16, 9, 2, 3, 10, 17, 24, 32, 25, 18, 11, 4, 5, 12, 19, 26, 33, 40, 48, 41, 34, 27, 20, 13, 6, 7, 14, 21, 28, 35,
  42, 49, 56, 57, 50, 43, 36, 29, 22, 15, 23, 30, 37, 44, 51, 58, 59, 52, 45, 38, 31, 39, 46, 53, 60, 61, 54, 47, 55, 62,
  63,
];

function scaledLuminance(quality: number): number[] {
  const scale = quality < 50 ? Math.floor(5000 / quality) : 200 - quality * 2;
  return ZIGZAG.map((natural) =>
    Math.min(255, Math.max(1, Math.floor((STANDARD_LUMINANCE[natural] * scale + 50) / 100))),
  );
}

function luminanceTable(bytes: Buffer): number[] | null {
  let offset = 2;
  while (offset + 4 <= bytes.length && bytes[offset] === 0xff) {
    const marker = bytes[offset + 1];
    const length = bytes.readUInt16BE(offset + 2);
    if (marker === START_OF_SCAN) {
      return null;
    }
    if (marker === DEFINE_QUANTIZATION) {
      let table = offset + 4;
      while (table < offset + 2 + length) {
        const precision = bytes[table] >> 4;
        const id = bytes[table] & 0x0f;
        const width = precision === 0 ? 1 : 2;
        if (id === 0) {
          return Array.from({ length: 64 }, (_, index) =>
            width === 1 ? bytes[table + 1 + index] : bytes.readUInt16BE(table + 1 + index * 2),
          );
        }
        table += 1 + 64 * width;
      }
    }
    offset += 2 + length;
  }
  return null;
}

export function jpegQuality(bytes: Buffer): number | null {
  const table = luminanceTable(bytes);
  if (table === null) {
    return null;
  }
  for (let quality = 100; quality >= 1; quality -= 1) {
    const expected = scaledLuminance(quality);
    if (expected.every((value, index) => value === table[index])) {
      return quality;
    }
  }
  return null;
}

export const JPEG_CAP_BYTES = 200 * 1024;

export function jpegSize(bytes: Buffer): { width: number; height: number } | null {
  if (bytes.length < 4 || bytes[0] !== 0xff || bytes[1] !== 0xd8) {
    return null;
  }
  let offset = 2;
  while (offset + 4 <= bytes.length) {
    if (bytes[offset] !== 0xff) {
      return null;
    }
    const marker = bytes[offset + 1];
    if (marker === 0xff) {
      offset += 1;
      continue;
    }
    if (marker === 0x01 || (marker >= 0xd0 && marker <= 0xd7)) {
      offset += 2;
      continue;
    }
    if (START_OF_FRAME.has(marker) && offset + 9 <= bytes.length) {
      return { height: bytes.readUInt16BE(offset + 5), width: bytes.readUInt16BE(offset + 7) };
    }
    offset += 2 + bytes.readUInt16BE(offset + 2);
  }
  return null;
}
