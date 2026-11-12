import { expect, test, type Page } from '@playwright/test';
import { MockBackend } from '../../support/mock-backend';
import { boxOf, monitorPage, startMonitoring } from '../../support/monitor-page';

function lightness(colour: string): number {
  const numbers = (colour.match(/-?\d*\.?\d+%?/g) ?? []).map((token) =>
    token.endsWith('%') ? Number.parseFloat(token) / 100 : Number.parseFloat(token),
  );
  if (colour.startsWith('oklch') || colour.startsWith('oklab')) {
    return numbers[0];
  }
  if (colour.startsWith('lab') || colour.startsWith('lch')) {
    return numbers[0] / 100;
  }
  const [red, green, blue] = colour.startsWith('color(') ? numbers : numbers.map((value) => value / 255);
  return 0.2126 * red + 0.7152 * green + 0.0722 * blue;
}

async function pageBackground(page: Page): Promise<number> {
  const colour = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
  return lightness(colour);
}

test.describe('monitor layout', () => {
  test('puts the video on the left, the heart rate top right and the pulse waveform below it', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    const backend = await MockBackend.attach(page);
    const monitor = monitorPage(page);
    await startMonitoring(page, backend);

    const video = await boxOf(monitor.video);
    const heartRate = await boxOf(monitor.heartRate);
    const quality = await boxOf(monitor.quality);
    const pulse = await boxOf(monitor.pulse);
    const hint = await boxOf(monitor.glanceNotice);

    expect(heartRate.x).toBeGreaterThanOrEqual(video.x + video.width - 1);
    expect(quality.x).toBeGreaterThanOrEqual(video.x + video.width - 1);
    expect(pulse.x).toBeGreaterThanOrEqual(video.x + video.width - 1);
    expect(heartRate.y).toBeLessThan(video.y + video.height / 2);
    expect(pulse.y).toBeGreaterThanOrEqual(heartRate.y + heartRate.height - 1);
    expect(hint.y).toBeGreaterThanOrEqual(video.y + video.height - 1);
    expect(hint.x).toBeLessThan(video.x + video.width);
  });

  test('stacks the panels vertically on a narrow screen', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    const backend = await MockBackend.attach(page);
    const monitor = monitorPage(page);
    await startMonitoring(page, backend);

    const video = await boxOf(monitor.video);
    const heartRate = await boxOf(monitor.heartRate);
    const pulse = await boxOf(monitor.pulse);

    expect(video.x + video.width).toBeLessThanOrEqual(390 + 1);
    expect(heartRate.y).toBeGreaterThanOrEqual(video.y + video.height - 1);
    expect(pulse.y).toBeGreaterThanOrEqual(heartRate.y + heartRate.height - 1);
  });

  test('follows the system colour scheme', async ({ page }) => {
    await page.emulateMedia({ colorScheme: 'dark' });
    await page.goto('/');

    await expect.poll(() => pageBackground(page)).toBeLessThan(0.35);

    await page.emulateMedia({ colorScheme: 'light' });

    await expect.poll(() => pageBackground(page)).toBeGreaterThan(0.65);
  });
});
