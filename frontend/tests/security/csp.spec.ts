import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { expect, test } from '@playwright/test';
import { build, preview, type PreviewServer } from 'vite';
import { MockBackend } from '../support/mock-backend';
import { collectPageErrors, monitorPage, videoIsPlaying } from '../support/monitor-page';

const FRONTEND_ROOT = fileURLToPath(new URL('../..', import.meta.url));

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

type Violations = { violations: string[] };

function parsePolicy(policy: string): Record<string, string[]> {
  return Object.fromEntries(
    policy
      .split(';')
      .map((directive) => directive.trim().split(/\s+/))
      .filter((tokens) => tokens[0] !== '')
      .map(([name, ...sources]) => [name, sources.toSorted()]),
  );
}

function sortedPolicy(policy: Record<string, string[]>): Record<string, string[]> {
  return Object.fromEntries(Object.entries(policy).map(([name, sources]) => [name, sources.toSorted()]));
}

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
  let outDir = '';
  let server: PreviewServer | null = null;

  test.beforeAll(async () => {
    outDir = mkdtempSync(join(tmpdir(), 'pulse-frame-build-'));
    await build({ root: FRONTEND_ROOT, logLevel: 'silent', build: { outDir, emptyOutDir: true } });
    server = await preview({
      root: FRONTEND_ROOT,
      logLevel: 'silent',
      build: { outDir },
      preview: { host: '127.0.0.1', port: 0, strictPort: false },
    });
  });

  test.afterAll(async () => {
    await server?.close();
    rmSync(outDir, { recursive: true, force: true });
  });

  test('builds index.html with the strict content security policy', () => {
    const policies = metaPolicies(readFileSync(join(outDir, 'index.html'), 'utf8'));

    expect(policies).toHaveLength(1);
    expect(parsePolicy(policies[0])).toEqual(sortedPolicy(EXPECTED_POLICY));
  });

  test('serves the built page with no content security policy violation while monitoring', async ({ page }) => {
    const errors = collectPageErrors(page);
    await page.addInitScript(() => {
      const record: Violations = { violations: [] };
      Object.defineProperty(globalThis, 'cspRecord', { value: record });
      document.addEventListener('securitypolicyviolation', (event) => {
        record.violations.push(`${event.violatedDirective} ${event.blockedURI}`);
      });
    });
    const backend = await MockBackend.attach(page);
    const monitor = monitorPage(page);
    const url = server?.resolvedUrls?.local[0] ?? '';
    expect(url).not.toBe('');

    await page.goto(url);
    await monitor.start.click();
    await expect.poll(() => backend.frames.length).toBeGreaterThan(3);
    await expect.poll(() => videoIsPlaying(monitor.video)).toBe(true);
    backend.pushReading({ bpm: 71.2, quality_db: 6.1, state: 'ok' });
    await expect(monitor.bpmValue).toHaveText(/^(71\.2|71)$/);

    const violations = await page.evaluate(() => (globalThis as unknown as Window & { cspRecord: Violations }).cspRecord.violations);
    expect(violations).toEqual([]);
    expect(errors).toEqual([]);
  });
});
