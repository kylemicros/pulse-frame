import { expect, test, type Locator } from '@playwright/test';
import {
  advanceRun,
  advanceRunUntil,
  expectCurrentStep,
  guidedPage,
  liveRegionsIn,
  pushAndConfirm,
  startRun,
  timerSeconds,
} from '../../support/guided-page';
import { faceScene, MockBackend, NO_FACE_SCENE, pulseSamples } from '../../support/mock-backend';
import { longestPathCommands, waveformSpan } from '../../support/page-helpers';

const NO_FACE_HINT = 'No face found. Face the camera.';
const BANDS = ['Weak', 'Fair', 'Good'] as const;
const QUALITY_EDGES = [
  { quality: 2.99, band: 'Weak' },
  { quality: 3, band: 'Fair' },
  { quality: 7.99, band: 'Fair' },
  { quality: 8, band: 'Good' },
] as const;

const WARM_UP_READING = { bpm: 72.4, quality_db: 5.1, state: 'ok' } as const;
const COUNTED_READING = { bpm: 67.2, quality_db: 9.1, state: 'ok' } as const;
const LOW_QUALITY_READING = { bpm: null, quality_db: 1.2, state: 'low_quality' } as const;

function faintestOpacity(value: Locator): Promise<number> {
  return value.evaluate((element) => {
    let faintest = 1;
    for (let node: Element | null = element; node !== null; node = node.parentElement) {
      faintest = Math.min(faintest, Number(getComputedStyle(node).opacity));
    }
    return faintest;
  });
}

function textColour(value: Locator): Promise<string> {
  return value.evaluate((element) => getComputedStyle(element).color);
}

function ownLiveSetting(region: Locator): Promise<string | null> {
  return region.evaluate((element) => {
    const live = element.getAttribute('aria-live');
    return live === 'off' ? null : live;
  });
}

test.describe('guided run live readings', () => {
  test('shows the live heart rate, signal quality and their 20 s window during the warm-up', async ({ page }) => {
    await page.clock.install();
    const backend = await MockBackend.attach(page);
    const guided = guidedPage(page);
    await startRun(page, backend);

    await pushAndConfirm(page, backend, WARM_UP_READING);

    await expect(guided.liveReadings.getByText(/^72(\.4)?$/)).toBeVisible();
    await expect(guided.liveReadings.getByText('BPM', { exact: true })).toBeVisible();
    await expect(guided.liveReadings.getByText('Fair', { exact: true })).toBeVisible();
    await expect(guided.liveReadings).toContainText('Last 20 s');
    await expect(guided.liveReadings).not.toContainText(/Settling/);
    await expect(guided.liveReadings).not.toContainText(/dB/);
    await expectCurrentStep(page, 'Warm-up');
  });

  test('keeps the heart rate, signal quality and pulse trace live while counting', async ({ page }) => {
    await page.clock.install();
    const backend = await MockBackend.attach(page);
    const guided = guidedPage(page);
    await startRun(page, backend);
    await advanceRunUntil(page, backend, guided.countedTimer);

    await pushAndConfirm(page, backend, COUNTED_READING);

    await expect(guided.liveReadings.getByText(/^67(\.2)?$/)).toBeVisible();
    await expect(guided.liveReadings.getByText('Good', { exact: true })).toBeVisible();
    await expect(guided.liveReadings).toContainText('Last 20 s');
    await expect(guided.pulseTrace).toHaveAccessibleName(/20 seconds/);
    await expect.poll(() => longestPathCommands(guided.pulseTrace)).toBeGreaterThan(10);
    await expect(guided.main.getByText('Pulse, last 20 s', { exact: true })).toBeVisible();
    await expectCurrentStep(page, 'Counted');
  });

  test('draws the pulse trace during the warm-up', async ({ page }) => {
    await page.clock.install();
    const backend = await MockBackend.attach(page);
    const guided = guidedPage(page);
    await startRun(page, backend);

    await pushAndConfirm(page, backend, WARM_UP_READING);

    await expect.poll(() => longestPathCommands(guided.pulseTrace)).toBeGreaterThan(10);
    await expectCurrentStep(page, 'Warm-up');
  });

  test('keeps the last good heart rate in a colour other than the live one, unfaded, with "Last good" when the signal drops', async ({
    page,
  }) => {
    await page.clock.install();
    const backend = await MockBackend.attach(page);
    const guided = guidedPage(page);
    await startRun(page, backend);
    await pushAndConfirm(page, backend, WARM_UP_READING);
    const value = guided.liveReadings.getByText(/^72(\.4)?$/);
    await expect(value).toBeVisible();
    await expect(guided.liveReadings.getByText('Last good', { exact: true })).toHaveCount(0);
    const liveColour = await textColour(value);

    await pushAndConfirm(page, backend, LOW_QUALITY_READING);
    await advanceRun(page, backend, 2000, 500);

    await expect(value).toBeVisible();
    await expect(guided.liveReadings.getByText('Last good', { exact: true })).toBeVisible();
    await expect(guided.liveReadings.getByText('No reading yet', { exact: true })).toHaveCount(0);
    expect(await textColour(value), 'the held value colour against the live value colour').not.toBe(liveColour);
    expect(await faintestOpacity(value)).toBe(1);
  });

  test('keeps the milestone output as the only live region in the panel while running', async ({ page }) => {
    await page.clock.install();
    const backend = await MockBackend.attach(page);
    const guided = guidedPage(page);
    await startRun(page, backend);
    await pushAndConfirm(page, backend, WARM_UP_READING);
    await expect(guided.liveReadings.getByText(/^72(\.4)?$/)).toBeVisible();

    expect(await liveRegionsIn(guided.main)).toEqual(['milestone-status']);
    expect(await ownLiveSetting(guided.liveReadings)).toBeNull();
    expect(await liveRegionsIn(guided.liveReadings)).toEqual([]);

    await advanceRunUntil(page, backend, guided.countedTimer);
    backend.setScene(faceScene({ moving: true }));
    await advanceRun(page, backend, 2000, 500);
    await expect(guided.main.getByText("You're moving. Hold still.", { exact: true })).toBeVisible();

    expect(await liveRegionsIn(guided.main)).toEqual(['milestone-status']);
    expect(await ownLiveSetting(guided.liveReadings)).toBeNull();
  });

  test('marks the empty part of the pulse trace as filling during the warm-up', async ({ page }) => {
    await page.clock.install();
    const backend = await MockBackend.attach(page);
    const guided = guidedPage(page);
    await startRun(page, backend);

    await expect(guided.main.getByText(/^Filling: \d+ of 20 s$/)).toBeVisible();
    await expect(guided.pulseTrace).toHaveAccessibleName(/20 seconds/);
  });

  test('shows the hold still hint when the user moves and keeps counting', async ({ page }) => {
    await page.clock.install();
    const backend = await MockBackend.attach(page);
    const guided = guidedPage(page);
    await startRun(page, backend);
    await advanceRunUntil(page, backend, guided.countedTimer);
    const before = await timerSeconds(guided.countedTimer);

    backend.setScene(faceScene({ moving: true }));
    await advanceRun(page, backend, 5000, 1000);

    await expect(guided.main.getByText("You're moving. Hold still.", { exact: true })).toBeVisible();
    await expectCurrentStep(page, 'Counted');
    await expect(guided.headline('Counting. Hold still.')).toBeVisible();
    expect(await timerSeconds(guided.countedTimer)).toBeLessThanOrEqual(before - 4);
  });

  test('names the signal quality band at its edges: under 3 dB Weak, 3 up to 8 dB Fair, from 8 dB Good', async ({
    page,
  }) => {
    await page.clock.install();
    const backend = await MockBackend.attach(page);
    const guided = guidedPage(page);
    await startRun(page, backend);

    for (const { quality, band } of QUALITY_EDGES) {
      await pushAndConfirm(page, backend, { bpm: 70.1, quality_db: quality, state: 'ok' });
      await advanceRun(page, backend, 500, 250);

      await expect(guided.liveReadings.getByText(band, { exact: true })).toBeVisible();
      for (const other of BANDS.filter((name) => name !== band)) {
        await expect(guided.liveReadings.getByText(other, { exact: true })).toHaveCount(0);
      }
    }
  });

  test('says no face was found under the camera while no face is in view', async ({ page }) => {
    await page.clock.install();
    const backend = await MockBackend.attach(page);
    const guided = guidedPage(page);
    await startRun(page, backend);
    await expect(guided.main.getByText(NO_FACE_HINT, { exact: true })).toHaveCount(0);

    backend.setScene(NO_FACE_SCENE);
    await advanceRun(page, backend, 2000, 500);

    await expect(guided.main.getByText(NO_FACE_HINT, { exact: true })).toBeVisible();

    backend.setScene(faceScene());
    await advanceRun(page, backend, 2000, 500);

    await expect(guided.main.getByText(NO_FACE_HINT, { exact: true })).toHaveCount(0);
  });

  test('keeps a fixed 20 s pulse window so an early 3 s trace fills only its right end', async ({ page }) => {
    const backend = await MockBackend.attach(page);
    const guided = guidedPage(page);
    await startRun(page, backend);

    backend.pushReading({ bpm: null, quality_db: null, state: 'acquiring' }, pulseSamples(90, 3000));

    await expect.poll(() => waveformSpan(guided.pulseTrace)).not.toBeNull();
    const early = await waveformSpan(guided.pulseTrace);
    expect(early?.widthShare).toBeGreaterThan(0.1);
    expect(early?.widthShare).toBeLessThan(0.2);
    expect(early?.rightGapShare).toBeLessThan(0.05);

    backend.pushReading({ bpm: 72.4, quality_db: 6.5, state: 'ok' }, pulseSamples(600, 23000));

    await expect.poll(async () => (await waveformSpan(guided.pulseTrace))?.widthShare).toBeGreaterThan(0.9);
  });

  test('clears the pulse trace when the pulse samples come back empty', async ({ page }) => {
    const backend = await MockBackend.attach(page);
    const guided = guidedPage(page);
    await startRun(page, backend);
    backend.pushReading({ bpm: 72.4, quality_db: 6.5, state: 'ok' }, pulseSamples(300));
    await expect.poll(() => longestPathCommands(guided.pulseTrace)).toBeGreaterThan(50);

    backend.pushReading({ bpm: null, quality_db: null, state: 'acquiring' }, []);

    await expect.poll(() => longestPathCommands(guided.pulseTrace)).toBeLessThan(5);
    await expect(guided.pulseTrace).toBeVisible();
  });
});
