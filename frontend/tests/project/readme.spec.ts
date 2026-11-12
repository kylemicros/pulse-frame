import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { expect, test } from '@playwright/test';

const README = fileURLToPath(new URL('../../../README.md', import.meta.url));

function readme(): string {
  return readFileSync(README, 'utf8');
}

test.describe('project README', () => {
  test('says daylight works and an evening lamp does not', () => {
    expect(readme()).toMatch(/daylight/i);
    expect(readme()).toMatch(/lamp/i);
  });

  test('says the privacy promise holds on macOS and MediaPipe may send its usage log on any Linux run', () => {
    const text = readme();

    expect(text).toMatch(/MediaPipe/);
    expect(text).toMatch(/usage log/i);
    expect(text).toMatch(/macOS/);
    expect(text).toMatch(/sandbox/i);
    expect(text).toMatch(/any Linux run/i);
    expect(text).toMatch(/\bCI\b/);
  });

  test('offers pnpm build and pnpm preview as the normal way to run the page', () => {
    const text = readme();

    expect(text).toMatch(/pnpm build && pnpm preview/);
    expect(text).toMatch(/pnpm dev/);
  });
});
