import { expect, test } from '@playwright/test';
import { MockBackend, pulseSamples } from '../../support/mock-backend';
import { longestPathCommands, monitorPage, startMonitoring, waveformSpan } from '../../support/monitor-page';

test.describe('pulse waveform', () => {
  test('draws the waveform from the pulse samples', async ({ page }) => {
    const backend = await MockBackend.attach(page);
    const monitor = monitorPage(page);
    await startMonitoring(page, backend);
    await expect(monitor.pulse).toBeVisible();

    backend.pushReading({ bpm: 72.4, quality_db: 6.5, state: 'ok' }, pulseSamples(300));

    await expect.poll(() => longestPathCommands(monitor.pulse)).toBeGreaterThan(50);
  });

  test('clears the waveform when the pulse samples are empty', async ({ page }) => {
    const backend = await MockBackend.attach(page);
    const monitor = monitorPage(page);
    await startMonitoring(page, backend);
    backend.pushReading({ bpm: 72.4, quality_db: 6.5, state: 'ok' }, pulseSamples(300));
    await expect.poll(() => longestPathCommands(monitor.pulse)).toBeGreaterThan(50);

    backend.pushReading({ bpm: null, quality_db: null, state: 'acquiring' }, []);

    await expect.poll(() => longestPathCommands(monitor.pulse)).toBeLessThan(5);
    await expect(monitor.pulse).toBeVisible();
  });

  test('keeps a fixed 20 s window so an early 3 s trace fills only its right end', async ({ page }) => {
    const backend = await MockBackend.attach(page);
    const monitor = monitorPage(page);
    await startMonitoring(page, backend);

    backend.pushReading({ bpm: null, quality_db: null, state: 'acquiring' }, pulseSamples(90, 3000));

    await expect.poll(() => waveformSpan(monitor.pulse)).not.toBeNull();
    const early = await waveformSpan(monitor.pulse);
    expect(early?.widthShare).toBeGreaterThan(0.1);
    expect(early?.widthShare).toBeLessThan(0.2);
    expect(early?.rightGapShare).toBeLessThan(0.05);

    backend.pushReading({ bpm: 72.4, quality_db: 6.5, state: 'ok' }, pulseSamples(600, 23000));

    await expect.poll(async () => (await waveformSpan(monitor.pulse))?.widthShare).toBeGreaterThan(0.9);
  });
});
