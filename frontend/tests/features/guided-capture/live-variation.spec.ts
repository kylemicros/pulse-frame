import { expect, test } from '@playwright/test';
import {
  advanceRun,
  advanceRunUntil,
  expectCurrentStep,
  guidedPage,
  OLD_VARIATION_LATER,
  pushAndConfirm,
  setHrvAndConfirm,
  startRun,
  termLines,
} from '../../support/guided-page';
import { hrv, MockBackend } from '../../support/mock-backend';

const BEAT_TO_BEAT = 'Beat to beat variation';
const OVERALL = 'Overall rhythm variation';
const NOT_YET = 'Not enough beats yet';
const COUNTED_READING = { bpm: 67.2, quality_db: 9.1, state: 'ok' } as const;

function ms(value: number) {
  return expect.stringMatching(new RegExp(`^${value} ?ms$`));
}

test.describe('guided run live variation', () => {
  test('reads "Not enough beats yet" and "Starts with counting" on both variation tiles through the warm-up', async ({
    page,
  }) => {
    await page.clock.install();
    const backend = await MockBackend.attach(page);
    const guided = guidedPage(page);
    await startRun(page, backend);

    await setHrvAndConfirm(page, backend, hrv());
    await advanceRun(page, backend, 2000, 500);

    await expectCurrentStep(page, 'Warm-up');
    await expect.poll(() => termLines(guided.liveReadings, BEAT_TO_BEAT)).toEqual([NOT_YET, 'Starts with counting']);
    await expect.poll(() => termLines(guided.liveReadings, OVERALL)).toEqual([NOT_YET, 'Starts with counting']);
    await expect(guided.variationLine).toBeVisible();
    await expect(guided.main.getByText(OLD_VARIATION_LATER)).toHaveCount(0);
  });

  test('fills the variation tiles from the newest message while counting, rounded half up to whole ms', async ({
    page,
  }) => {
    await page.clock.install();
    const backend = await MockBackend.attach(page);
    const guided = guidedPage(page);
    await startRun(page, backend);
    await advanceRunUntil(page, backend, guided.countedTimer);
    await pushAndConfirm(page, backend, COUNTED_READING);

    await setHrvAndConfirm(page, backend, hrv({ rmssd_ms: 38.5, minute_count: 20 }));
    await advanceRun(page, backend, 1000, 250);

    await expect.poll(() => termLines(guided.liveReadings, BEAT_TO_BEAT)).toEqual([ms(39), 'Counted part so far']);
    await expect.poll(() => termLines(guided.liveReadings, OVERALL)).toEqual([NOT_YET, 'Newest counted minute']);
    await expect(guided.variationLine).toBeVisible();

    await setHrvAndConfirm(page, backend, hrv({ rmssd_ms: 40.5, sdnn_ms: 44.5, minute_bpm: 66.8, minute_count: 50 }));
    await advanceRun(page, backend, 1000, 250);

    await expect.poll(() => termLines(guided.liveReadings, BEAT_TO_BEAT)).toEqual([ms(41), 'Counted part so far']);
    await expect.poll(() => termLines(guided.liveReadings, OVERALL)).toEqual([ms(45), 'Newest counted minute']);

    await setHrvAndConfirm(page, backend, hrv({ rmssd_ms: 38.4, sdnn_ms: 47.49, minute_bpm: 66.8, minute_count: 55 }));
    await advanceRun(page, backend, 1000, 250);

    await expect.poll(() => termLines(guided.liveReadings, BEAT_TO_BEAT)).toEqual([ms(38), 'Counted part so far']);
    await expect.poll(() => termLines(guided.liveReadings, OVERALL)).toEqual([ms(47), 'Newest counted minute']);
    await expect(guided.liveReadings.getByText(/^67(\.2)?$/)).toBeVisible();
    await expect(guided.liveReadings).not.toContainText(/RMSSD|SDNN|\b(high|low|normal|abnormal)\b/i);
    await expectCurrentStep(page, 'Counted');
  });

  test('goes back to "Not enough beats yet" when a later message has no variation values', async ({ page }) => {
    await page.clock.install();
    const backend = await MockBackend.attach(page);
    const guided = guidedPage(page);
    await startRun(page, backend);
    await advanceRunUntil(page, backend, guided.countedTimer);
    await setHrvAndConfirm(page, backend, hrv({ rmssd_ms: 36.2, sdnn_ms: 42.7, minute_bpm: 70.1, minute_count: 50 }));
    await advanceRun(page, backend, 1000, 250);
    await expect.poll(() => termLines(guided.liveReadings, BEAT_TO_BEAT)).toEqual([ms(36), 'Counted part so far']);

    await setHrvAndConfirm(page, backend, hrv({ minute_count: 10 }));
    await advanceRun(page, backend, 1000, 250);

    await expect.poll(() => termLines(guided.liveReadings, BEAT_TO_BEAT)).toEqual([NOT_YET, 'Counted part so far']);
    await expect.poll(() => termLines(guided.liveReadings, OVERALL)).toEqual([NOT_YET, 'Newest counted minute']);
    await expect(guided.liveReadings).not.toContainText(/\b(36|43)\b/);
  });
});
