import type { Locator, Page } from '@playwright/test';

export type Size = { width: number; height: number };

export type PngHeader = Size & { signature: string; firstChunk: string };

export type IcoHeader = { reserved: number; type: number; entries: Size[] };

export type SvgReport = { root: string; viewBox: string | null; findings: string[] };

export type Paint = { paint: 'fill' | 'stroke'; colour: string };

export type MaskableReport = { size: Size; cornerAlphas: number[]; markPixels: number; farthestMarkPixel: number };

export const HOP_BLUE = 'rgb(0, 114, 178)';
export const HOP_VERMILION = 'rgb(213, 94, 0)';

export const PNG_SIGNATURE = '89504e470d0a1a0a';
const MARK_COLOUR_DISTANCE = 96;
const SVG_ANIMATIONS = ['animate', 'set', 'animateMotion', 'animateTransform'];

export function headerLogo(page: Page) {
  const banner = page.getByRole('banner');
  return {
    banner,
    wordmark: banner.getByRole('heading', { level: 1, name: 'pulse frame', exact: true }),
    mark: banner.getByTestId('brand-mark'),
  };
}

export function readPngHeader(bytes: Buffer): PngHeader {
  return {
    signature: bytes.subarray(0, 8).toString('hex'),
    firstChunk: bytes.subarray(12, 16).toString('latin1'),
    width: bytes.readUInt32BE(16),
    height: bytes.readUInt32BE(20),
  };
}

export function readIcoHeader(bytes: Buffer): IcoHeader {
  const count = bytes.readUInt16LE(4);
  const entries = Array.from({ length: count }, (_, index) => {
    const offset = 6 + index * 16;
    return { width: bytes[offset] || 256, height: bytes[offset + 1] || 256 };
  });
  return { reserved: bytes.readUInt16LE(0), type: bytes.readUInt16LE(2), entries };
}

export function decodedSize(page: Page, url: string): Promise<Size> {
  return page.evaluate(async (source) => {
    const image = new Image();
    image.src = source;
    await image.decode();
    return { width: image.naturalWidth, height: image.naturalHeight };
  }, url);
}

export function inspectSvg(page: Page, text: string): Promise<SvgReport> {
  return page.evaluate(({ source, animations }) => {
    const doc = new DOMParser().parseFromString(source, 'image/svg+xml');
    const findings: string[] = [];
    if (doc.getElementsByTagName('parsererror').length > 0) {
      findings.push('the file does not parse as SVG');
    }
    if (doc.doctype !== null) {
      findings.push(`a doctype ${doc.doctype.name}`);
    }
    const styles: string[] = [];
    for (const element of Array.from(doc.getElementsByTagName('*'))) {
      const name = element.localName;
      if (name === 'script' || name.toLowerCase() === 'foreignobject') {
        findings.push(`a ${name} element`);
      }
      if (animations.includes(name)) {
        findings.push(`an animation element: ${name}`);
      }
      if (name === 'style') {
        styles.push(element.textContent ?? '');
      }
      for (const attribute of Array.from(element.attributes)) {
        const attributeName = attribute.localName.toLowerCase();
        if (attributeName.startsWith('on')) {
          findings.push(`an ${attribute.name} attribute on ${name}`);
        }
        if (attributeName === 'href' && !attribute.value.trim().startsWith('#')) {
          findings.push(`an external ${attribute.name} on ${name}: ${attribute.value}`);
        }
        if (attributeName === 'style') {
          styles.push(attribute.value);
        }
      }
    }
    for (const style of styles) {
      if (/@import/i.test(style)) {
        findings.push('an @import in a style');
      }
      for (const match of style.matchAll(/url\(\s*['"]?([^'")\s]*)/gi)) {
        if (!match[1].startsWith('#')) {
          findings.push(`an external url() in a style: ${match[1]}`);
        }
      }
    }
    const root = doc.documentElement;
    return { root: root.localName, viewBox: root.getAttribute('viewBox'), findings };
  }, { source: text, animations: SVG_ANIMATIONS });
}

export function tileColour(page: Page, url: string, size: number): Promise<string> {
  return page.evaluate(
    async ({ source, side }) => {
      const image = new Image(side, side);
      image.src = source;
      await image.decode();
      const canvas = document.createElement('canvas');
      canvas.width = side;
      canvas.height = side;
      const context = canvas.getContext('2d');
      if (context === null) {
        throw new Error('No 2d canvas context');
      }
      context.drawImage(image, 0, 0, side, side);
      const data = context.getImageData(0, 0, side, side).data;
      const counts = new Map<string, number>();
      for (let index = 0; index < data.length; index += 4) {
        if (data[index + 3] === 255) {
          const colour = `rgb(${data[index]}, ${data[index + 1]}, ${data[index + 2]})`;
          counts.set(colour, (counts.get(colour) ?? 0) + 1);
        }
      }
      const ranked = Array.from(counts.entries()).toSorted((a, b) => b[1] - a[1]);
      if (ranked.length === 0) {
        throw new Error('The icon paints no opaque pixel');
      }
      return ranked[0][0];
    },
    { source: url, side: size },
  );
}

export function paintedColours(mark: Locator): Promise<Paint[]> {
  return mark.evaluate((svg) => {
    const paints: Array<{ paint: 'fill' | 'stroke'; colour: string }> = [];
    for (const shape of Array.from(svg.querySelectorAll('*'))) {
      if (!(shape instanceof SVGGeometryElement)) {
        continue;
      }
      const style = getComputedStyle(shape);
      if (style.display === 'none' || style.visibility === 'hidden') {
        continue;
      }
      if (style.stroke !== 'none' && Number.parseFloat(style.strokeWidth) > 0) {
        paints.push({ paint: 'stroke', colour: style.stroke });
      }
      if (style.fill !== 'none') {
        paints.push({ paint: 'fill', colour: style.fill });
      }
    }
    return paints;
  });
}

export function backgroundBehind(element: Locator): Promise<string> {
  return element.evaluate((start) => {
    let node: Element | null = start;
    while (node !== null) {
      const colour = getComputedStyle(node).backgroundColor;
      if (colour !== 'transparent' && colour !== 'rgba(0, 0, 0, 0)') {
        return colour;
      }
      node = node.parentElement;
    }
    return 'rgb(255, 255, 255)';
  });
}

function channels(colour: string): number[] {
  const values = colour.match(/[\d.]+/g);
  if (values === null || values.length < 3) {
    throw new Error(`Cannot read the colour ${colour}`);
  }
  return values.slice(0, 3).map(Number);
}

function luminance(colour: string): number {
  const [red, green, blue] = channels(colour).map((value) => {
    const channel = value / 255;
    return channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * red + 0.7152 * green + 0.0722 * blue;
}

export function contrastRatio(first: string, second: string): number {
  const [light, dark] = [luminance(first), luminance(second)].toSorted((a, b) => b - a);
  return (light + 0.05) / (dark + 0.05);
}

export function inspectMaskable(page: Page, url: string): Promise<MaskableReport> {
  return page.evaluate(
    async ({ source, threshold }) => {
      const image = new Image();
      image.src = source;
      await image.decode();
      const width = image.naturalWidth;
      const height = image.naturalHeight;
      const canvas = document.createElement('canvas');
      canvas.width = width;
      canvas.height = height;
      const context = canvas.getContext('2d');
      if (context === null) {
        throw new Error('No 2d canvas context');
      }
      context.drawImage(image, 0, 0);
      const data = context.getImageData(0, 0, width, height).data;
      const at = (x: number, y: number) => data.subarray((y * width + x) * 4, (y * width + x) * 4 + 4);
      const corners = [at(0, 0), at(width - 1, 0), at(0, height - 1), at(width - 1, height - 1)];
      const background = corners[0];
      let markPixels = 0;
      let farthestMarkPixel = 0;
      for (let y = 0; y < height; y += 1) {
        for (let x = 0; x < width; x += 1) {
          const pixel = at(x, y);
          const distance =
            Math.abs(pixel[0] - background[0]) + Math.abs(pixel[1] - background[1]) + Math.abs(pixel[2] - background[2]);
          if (distance > threshold) {
            markPixels += 1;
            farthestMarkPixel = Math.max(farthestMarkPixel, Math.hypot(x + 0.5 - width / 2, y + 0.5 - height / 2));
          }
        }
      }
      return {
        size: { width, height },
        cornerAlphas: corners.map((corner) => corner[3]),
        markPixels,
        farthestMarkPixel,
      };
    },
    { source: url, threshold: MARK_COLOUR_DISTANCE },
  );
}
