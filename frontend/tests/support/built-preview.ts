import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import type { Page } from '@playwright/test';
import { build, preview } from 'vite';

type CspRecord = { violations: string[] };

type CspWindow = Window & { cspRecord: CspRecord };

export async function recordCspViolations(page: Page): Promise<void> {
  await page.addInitScript(() => {
    const record: CspRecord = { violations: [] };
    Object.defineProperty(globalThis, 'cspRecord', { value: record });
    document.addEventListener('securitypolicyviolation', (event) => {
      record.violations.push(`${event.violatedDirective} ${event.blockedURI}`);
    });
  });
}

export function cspViolations(page: Page): Promise<string[]> {
  return page.evaluate(() => [...(globalThis as unknown as CspWindow).cspRecord.violations]);
}

export const FRONTEND_ROOT = fileURLToPath(new URL('../..', import.meta.url));

export type BuiltSite = { outDir: string; remove: () => void };

export type BuiltPreview = BuiltSite & { url: string; close: () => Promise<void> };

export async function buildSite(): Promise<BuiltSite> {
  const outDir = mkdtempSync(join(tmpdir(), 'pulse-frame-build-'));
  await build({ root: FRONTEND_ROOT, logLevel: 'silent', build: { outDir, emptyOutDir: true } });
  return { outDir, remove: () => rmSync(outDir, { recursive: true, force: true }) };
}

export async function startBuiltPreview(): Promise<BuiltPreview> {
  const site = await buildSite();
  const server = await preview({
    root: FRONTEND_ROOT,
    logLevel: 'silent',
    build: { outDir: site.outDir },
    preview: { host: '127.0.0.1', port: 0, strictPort: false },
  });
  const url = server.resolvedUrls?.local[0] ?? '';
  return {
    ...site,
    url,
    close: async () => {
      await server.close();
      site.remove();
    },
  };
}
