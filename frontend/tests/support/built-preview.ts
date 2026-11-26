import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { build, preview } from 'vite';

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
