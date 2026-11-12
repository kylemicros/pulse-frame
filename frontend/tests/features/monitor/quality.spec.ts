import { expect, test } from '@playwright/test';
import { MockBackend } from '../../support/mock-backend';
import { monitorPage, startMonitoring } from '../../support/monitor-page';

test.describe('signal quality', () => {
  test('shows the quality in dB with its band', async ({ page }) => {
    const backend = await MockBackend.attach(page);
    const monitor = monitorPage(page);
    await startMonitoring(page, backend);

    backend.pushReading({ bpm: 74.6, quality_db: 5.21, state: 'ok' });

    await expect(monitor.quality).toContainText('5.21');
    await expect(monitor.quality).toContainText(/dB/);
    await expect(monitor.quality.getByText(/^fair$/i)).toBeVisible();
  });

  test('bands quality as weak below 3 dB, fair from 3 dB and good from 8 dB', async ({ page }) => {
    const backend = await MockBackend.attach(page);
    const monitor = monitorPage(page);
    await startMonitoring(page, backend);

    const bands = [
      { quality_db: 2.99, band: /^weak$/i, state: 'low_quality' as const, bpm: null },
      { quality_db: 3, band: /^fair$/i, state: 'ok' as const, bpm: 70.1 },
      { quality_db: 7.99, band: /^fair$/i, state: 'ok' as const, bpm: 70.2 },
      { quality_db: 8, band: /^good$/i, state: 'ok' as const, bpm: 70.3 },
    ];
    for (const { quality_db, band, state, bpm } of bands) {
      backend.pushReading({ bpm, quality_db, state });

      await expect(monitor.quality).toContainText(String(quality_db));
      await expect(monitor.quality.getByText(band)).toBeVisible();
    }
  });

  test('shows no quality number when quality_db is null', async ({ page }) => {
    const backend = await MockBackend.attach(page);
    const monitor = monitorPage(page);
    await startMonitoring(page, backend);
    backend.pushReading({ bpm: 74.6, quality_db: 5.21, state: 'ok' });
    await expect(monitor.quality).toContainText('5.21');

    backend.pushReading({ bpm: null, quality_db: null, state: 'low_quality' });

    await expect(monitor.quality).toContainText(/no value/i);
    await expect(monitor.quality).not.toContainText(/\d/);
    await expect(monitor.quality.getByText(/^(weak|fair|good)$/i)).toHaveCount(0);
  });
});
