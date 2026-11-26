import { join } from 'node:path';
import { expect, test } from '@playwright/test';
import { loadConfig } from 'svgo';
import { FRONTEND_ROOT } from '../support/built-preview';

async function pluginNames(): Promise<string[]> {
  const config = await loadConfig(join(FRONTEND_ROOT, 'svgo.config.mjs'));
  return (config.plugins ?? []).map((plugin) => (typeof plugin === 'string' ? plugin : plugin.name));
}

test.describe('SVGO config', () => {
  test('runs the default preset with removeScripts and never removeViewBox', async () => {
    const names = await pluginNames();

    expect(names).toContain('preset-default');
    expect(names).toContain('removeScripts');
    expect(names).not.toContain('removeViewBox');
  });
});
