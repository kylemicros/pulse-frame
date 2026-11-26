import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { expect, test, type APIRequestContext, type Page } from '@playwright/test';
import {
  backgroundBehind,
  contrastRatio,
  decodedSize,
  headerLogo,
  HOP_BLUE,
  HOP_VERMILION,
  inspectMaskable,
  inspectSvg,
  paintedColours,
  PNG_SIGNATURE,
  readIcoHeader,
  readPngHeader,
  tileColour,
} from './support/brand';
import { FRONTEND_ROOT, startBuiltPreview, type BuiltPreview } from './support/built-preview';
import { boxOf } from './support/page-helpers';

type HeadLink = { rel: string; href: string | null; sizes: string | null; type: string | null };

type ManifestIcon = { src: string; sizes?: string; type?: string; purpose?: string };

type Manifest = { name?: string; theme_color?: string; background_color?: string; icons?: ManifestIcon[] };

const ICON_RELS = ['icon', 'shortcut', 'apple-touch-icon', 'apple-touch-icon-precomposed', 'mask-icon', 'manifest'];

const APPROVED_LINKS: HeadLink[] = [
  { rel: 'apple-touch-icon', href: '/apple-touch-icon.png', sizes: null, type: null },
  { rel: 'icon', href: '/favicon.ico', sizes: '32x32', type: null },
  { rel: 'icon', href: '/icon.svg', sizes: null, type: 'image/svg+xml' },
  { rel: 'manifest', href: '/manifest.webmanifest', sizes: null, type: null },
];

const CONTENT_TYPES: Record<string, RegExp> = {
  '/favicon.ico': /^image\/(x-icon|vnd\.microsoft\.icon)$/,
  '/icon.svg': /^image\/svg\+xml(;.*)?$/,
  '/apple-touch-icon.png': /^image\/png$/,
  '/manifest.webmanifest': /^application\/manifest\+json(;.*)?$/,
};

const HEX_COLOUR = /^#[0-9a-f]{6}$/i;
const SAFE_CIRCLE_SHARE = 0.4;
const MIN_LOGO_CONTRAST = 3;
const DARK_TAB = 'rgb(20, 20, 20)';
const ICON_RENDER_PX = 64;

function headLinks(page: Page): Promise<HeadLink[]> {
  return page.locator('head link').evaluateAll((links, rels) =>
    links
      .map((link) => ({
        rel: link.getAttribute('rel') ?? '',
        href: link.getAttribute('href'),
        sizes: link.getAttribute('sizes'),
        type: link.getAttribute('type'),
      }))
      .filter((link) => link.rel.toLowerCase().split(/\s+/).some((token) => rels.includes(token))),
    ICON_RELS,
  );
}

function sortedLinks(links: HeadLink[]): HeadLink[] {
  return links.toSorted((a, b) => `${a.rel} ${a.href}`.localeCompare(`${b.rel} ${b.href}`));
}

async function fetchBytes(request: APIRequestContext, url: string): Promise<{ status: number; type: string; body: Buffer }> {
  const response = await request.get(url);
  return { status: response.status(), type: response.headers()['content-type'] ?? '', body: await response.body() };
}

async function servedFile(request: APIRequestContext, url: string, type: RegExp, by = 'the built preview'): Promise<Buffer> {
  const file = await fetchBytes(request, url);
  expect(file.status, `${url} is not served by ${by}`).toBe(200);
  expect(file.type, `${url} is not served by ${by} with its own content type`).toMatch(type);
  return file.body;
}

async function readManifest(request: APIRequestContext, base: string): Promise<{ url: string; manifest: Manifest }> {
  const url = new URL('/manifest.webmanifest', base).href;
  const body = await servedFile(request, url, CONTENT_TYPES['/manifest.webmanifest']);
  return { url, manifest: JSON.parse(body.toString('utf8')) as Manifest };
}

test.describe('icon set in the built page', () => {
  test.describe.configure({ mode: 'default' });

  let site: BuiltPreview | null = null;

  test.beforeAll(async () => {
    site = await startBuiltPreview();
  });

  test.afterAll(async () => {
    await site?.close();
  });

  function siteUrl(path = '/'): string {
    const base = site?.url ?? '';
    expect(base).not.toBe('');
    return new URL(path, base).href;
  }

  test('links exactly the approved icon set in the page head', async ({ page }) => {
    await page.goto(siteUrl());

    expect(sortedLinks(await headLinks(page))).toEqual(APPROVED_LINKS);
  });

  test('sets light and dark theme colours and no legacy tile metas', async ({ page }) => {
    await page.goto(siteUrl());

    const themeColours = await page
      .locator('head meta[name="theme-color"]')
      .evaluateAll((metas) =>
        metas.map((meta) => ({ media: meta.getAttribute('media'), content: meta.getAttribute('content') })),
      );
    expect(themeColours.toSorted((a, b) => (a.media ?? '').localeCompare(b.media ?? ''))).toEqual([
      { media: '(prefers-color-scheme: dark)', content: expect.stringMatching(HEX_COLOUR) },
      { media: '(prefers-color-scheme: light)', content: expect.stringMatching(HEX_COLOUR) },
    ]);
    await expect(page.locator('head meta[name^="msapplication"]')).toHaveCount(0);
  });

  test('drops the broken favicon.svg link from the HTML entry and the built page', () => {
    const source = readFileSync(join(FRONTEND_ROOT, 'index.html'), 'utf8');
    const outDir = site?.outDir ?? '';
    expect(outDir).not.toBe('');
    const built = readFileSync(join(outDir, 'index.html'), 'utf8');

    expect(source).not.toContain('favicon.svg');
    expect(built).not.toContain('favicon.svg');
  });

  test('serves every linked icon file with its content type', async ({ page, request }) => {
    await page.goto(siteUrl());
    const hrefs = (await headLinks(page)).map((link) => link.href ?? '');
    expect(hrefs.toSorted()).toEqual(Object.keys(CONTENT_TYPES).toSorted());

    for (const href of hrefs) {
      const body = await servedFile(request, siteUrl(href), CONTENT_TYPES[href]);
      expect(body.length, `${href} is empty`).toBeGreaterThan(0);
    }
  });

  test('serves favicon.ico as a 32x32 icon', async ({ page, request }) => {
    const body = await servedFile(request, siteUrl('/favicon.ico'), CONTENT_TYPES['/favicon.ico']);

    const header = readIcoHeader(body);
    expect(header.reserved).toBe(0);
    expect(header.type, 'not an ICO icon directory').toBe(1);
    expect(header.entries).toEqual([{ width: 32, height: 32 }]);
    await page.goto(siteUrl());
    expect(await decodedSize(page, siteUrl('/favicon.ico'))).toEqual({ width: 32, height: 32 });
  });

  test('serves apple-touch-icon.png as a 180x180 PNG', async ({ page, request }) => {
    const body = await servedFile(request, siteUrl('/apple-touch-icon.png'), CONTENT_TYPES['/apple-touch-icon.png']);

    expect(readPngHeader(body)).toEqual({ signature: PNG_SIGNATURE, firstChunk: 'IHDR', width: 180, height: 180 });
    await page.goto(siteUrl());
    expect(await decodedSize(page, siteUrl('/apple-touch-icon.png'))).toEqual({ width: 180, height: 180 });
  });

  test('lists the 192, 512 and maskable 512 icons with the name and theme colours in the manifest', async ({
    request,
  }) => {
    const { manifest } = await readManifest(request, siteUrl());

    expect(manifest.name).toBe('pulse-frame');
    expect(manifest.theme_color).toMatch(HEX_COLOUR);
    expect(manifest.background_color).toMatch(HEX_COLOUR);
    const icons = (manifest.icons ?? []).map((icon) => ({
      sizes: icon.sizes,
      type: icon.type,
      purpose: icon.purpose ?? 'any',
    }));
    expect(icons.toSorted((a, b) => `${a.sizes} ${a.purpose}`.localeCompare(`${b.sizes} ${b.purpose}`))).toEqual([
      { sizes: '192x192', type: 'image/png', purpose: 'any' },
      { sizes: '512x512', type: 'image/png', purpose: 'any' },
      { sizes: '512x512', type: 'image/png', purpose: 'maskable' },
    ]);
  });

  test('serves every manifest icon as a PNG of its listed size', async ({ page, request }) => {
    const { url, manifest } = await readManifest(request, siteUrl());
    const icons = manifest.icons ?? [];
    expect(icons).toHaveLength(3);
    await page.goto(siteUrl());

    for (const icon of icons) {
      const iconUrl = new URL(icon.src, url).href;
      const [width, height] = (icon.sizes ?? '').split('x').map(Number);
      const body = await servedFile(request, iconUrl, /^image\/png$/);

      expect(readPngHeader(body)).toEqual({ signature: PNG_SIGNATURE, firstChunk: 'IHDR', width, height });
      expect(await decodedSize(page, iconUrl)).toEqual({ width, height });
    }
  });

  test('keeps the maskable icon mark inside the central 40 percent circle on a full bleed tile', async ({
    page,
    request,
  }) => {
    const { url, manifest } = await readManifest(request, siteUrl());
    const maskable = (manifest.icons ?? []).filter((icon) => icon.purpose === 'maskable');
    expect(maskable).toHaveLength(1);
    await page.goto(siteUrl());

    const report = await inspectMaskable(page, new URL(maskable[0].src, url).href);

    expect(report.size).toEqual({ width: 512, height: 512 });
    expect(report.cornerAlphas, 'the maskable tile does not fill to the corners').toEqual([255, 255, 255, 255]);
    expect(report.markPixels, 'no mark on the maskable tile').toBeGreaterThan(0);
    expect(report.farthestMarkPixel, 'the mark reaches outside the safe circle').toBeLessThanOrEqual(
      SAFE_CIRCLE_SHARE * report.size.width,
    );
  });

  test('serves icon.svg as a safe blue Hop tile with a viewBox from 0 0', async ({
    page,
    request,
  }) => {
    const body = await servedFile(request, siteUrl('/icon.svg'), CONTENT_TYPES['/icon.svg']);
    const text = body.toString('utf8');
    await page.goto(siteUrl());

    const report = await inspectSvg(page, text);

    expect(report.root).toBe('svg');
    expect(report.viewBox, 'icon.svg lost its viewBox').toMatch(/^\s*0[ ,]+0[ ,]+\d+(\.\d+)?[ ,]+\d+(\.\d+)?\s*$/);
    expect(report.findings, 'unsafe content in icon.svg').toEqual([]);
    expect(text.toLowerCase()).toContain('#0072b2');
  });

  test('paints the icon.svg tile at 3 to 1 or more against the dark theme colour so it reads on a dark tab', async ({
    page,
  }) => {
    await page.emulateMedia({ colorScheme: 'dark' });
    await page.goto(siteUrl());
    await expect(page.locator('head meta[name="theme-color"][media="(prefers-color-scheme: dark)"]')).toHaveAttribute(
      'content',
      /^#141414$/i,
    );

    const tile = await tileColour(page, siteUrl('/icon.svg'), ICON_RENDER_PX);

    expect(contrastRatio(tile, DARK_TAB), `the tile ${tile} on ${DARK_TAB}`).toBeGreaterThanOrEqual(MIN_LOGO_CONTRAST);
  });
});

test.describe('header logo', () => {
  test('shows the Hop mark hidden from screen readers beside the pulse-frame wordmark', async ({ page }) => {
    await page.goto('/');
    const logo = headerLogo(page);

    await expect(page.getByRole('heading', { level: 1 })).toHaveCount(1);
    await expect(logo.wordmark).toBeVisible();
    await expect(logo.wordmark).toHaveText('pulse-frame');
    await expect(logo.mark).toHaveCount(1);
    await expect(logo.mark).toBeVisible();
    await expect(logo.mark).toHaveAttribute('viewBox', /\S/);
    await expect(logo.wordmark.locator('svg'), 'the mark sits inside the heading instead of beside it').toHaveCount(0);

    const markBox = await boxOf(logo.mark);
    const wordBox = await boxOf(logo.wordmark);
    expect(markBox.width).toBeGreaterThanOrEqual(16);
    expect(markBox.height).toBeGreaterThanOrEqual(16);
    expect(markBox.x + markBox.width, 'the mark does not sit before the wordmark').toBeLessThanOrEqual(wordBox.x + 1);
    expect(wordBox.x - (markBox.x + markBox.width), 'the mark is not beside the wordmark').toBeLessThanOrEqual(24);
    expect(
      Math.abs(markBox.y + markBox.height / 2 - (wordBox.y + wordBox.height / 2)),
      'the mark is not level with the wordmark',
    ).toBeLessThanOrEqual(markBox.height / 2);
  });

  for (const colorScheme of ['light', 'dark'] as const) {
    test(`paints the header mark in Hop blue and vermilion at 3 to 1 or more on the ${colorScheme} page`, async ({
      page,
    }) => {
      await page.emulateMedia({ colorScheme });
      await page.goto('/');
      const logo = headerLogo(page);
      await expect(logo.mark).toBeVisible();

      const paints = await paintedColours(logo.mark);
      const background = await backgroundBehind(logo.mark);

      expect(paints.filter((paint) => paint.paint === 'stroke').map((paint) => paint.colour)).toEqual([HOP_BLUE]);
      expect(paints.filter((paint) => paint.paint === 'fill').map((paint) => paint.colour)).toEqual([HOP_VERMILION]);
      for (const { colour } of paints) {
        expect(contrastRatio(colour, background), `${colour} on ${background}`).toBeGreaterThanOrEqual(
          MIN_LOGO_CONTRAST,
        );
      }
    });
  }

  test('resolves every icon link on the dev server', async ({ page, request }) => {
    await page.goto('/');
    const hrefs = (await headLinks(page)).map((link) => link.href ?? '');
    expect(hrefs.toSorted()).toEqual(Object.keys(CONTENT_TYPES).toSorted());

    for (const href of hrefs) {
      await servedFile(request, href, CONTENT_TYPES[href], 'the dev server');
    }
  });
});
