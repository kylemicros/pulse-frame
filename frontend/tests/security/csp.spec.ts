import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { expect, test } from '@playwright/test';
import { cspViolations, recordCspViolations, startBuiltPreview, type BuiltPreview } from '../support/built-preview';
import { parsePolicy, sortedPolicy } from '../support/csp-policy';
import { guidedPage } from '../support/guided-page';
import { MockBackend } from '../support/mock-backend';
import { collectPageErrors, longestPathCommands, videoIsPlaying } from '../support/page-helpers';

const EXPECTED_POLICY: Record<string, string[]> = {
  'default-src': ["'self'"],
  'connect-src': ['ws://127.0.0.1:8000'],
  'img-src': ["'self'", 'blob:', 'data:'],
  'media-src': ["'self'", 'blob:'],
  'style-src': ["'self'"],
  'script-src': ["'self'"],
  'object-src': ["'none'"],
  'base-uri': ["'none'"],
  'form-action': ["'none'"],
};

const HTML_ENTITIES: Record<string, string> = {
  '&#39;': "'",
  '&#x27;': "'",
  '&apos;': "'",
  '&quot;': '"',
  '&#34;': '"',
  '&lt;': '<',
  '&gt;': '>',
  '&amp;': '&',
};

function decodeEntities(value: string): string {
  return value.replaceAll(/&(?:#39|#x27|apos|quot|#34|lt|gt|amp);/gi, (entity) => HTML_ENTITIES[entity.toLowerCase()]);
}

function metaPolicies(html: string): string[] {
  return Array.from(
    html.matchAll(/<meta\s+http-equiv="Content-Security-Policy"\s+content="([^"]*)"/gi),
    (match) => decodeEntities(match[1]),
  );
}

test.describe('content security policy', () => {
  let site: BuiltPreview | null = null;

  test.beforeAll(async () => {
    site = await startBuiltPreview();
  });

  test.afterAll(async () => {
    await site?.close();
  });

  test('builds index.html with the strict content security policy', () => {
    const outDir = site?.outDir ?? '';
    expect(outDir).not.toBe('');
    const policies = metaPolicies(readFileSync(join(outDir, 'index.html'), 'utf8'));

    expect(policies).toHaveLength(1);
    expect(parsePolicy(policies[0])).toEqual(sortedPolicy(EXPECTED_POLICY));
  });

  test('serves the built page with no content security policy violation during a guided run with the skin outline', async ({ page }) => {
    const errors = collectPageErrors(page);
    await recordCspViolations(page);
    const backend = await MockBackend.attach(page);
    const guided = guidedPage(page);
    const url = site?.url ?? '';
    expect(url).not.toBe('');

    await page.goto(url);
    await guided.start.click();
    await expect.poll(() => backend.frames.length).toBeGreaterThan(3);
    await expect.poll(() => videoIsPlaying(guided.video)).toBe(true);
    await expect(guided.outlines).toHaveCount(3);
    backend.pushReading({ bpm: 71.2, quality_db: 6.1, state: 'ok' });
    await expect(guided.liveReadings.getByText(/^(71\.2|71)$/)).toBeVisible();
    await expect.poll(() => longestPathCommands(guided.pulseTrace)).toBeGreaterThan(10);

    expect(await cspViolations(page)).toEqual([]);
    expect(errors).toEqual([]);
  });
});
