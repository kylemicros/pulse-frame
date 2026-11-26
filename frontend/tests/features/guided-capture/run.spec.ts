import { expect, test } from '@playwright/test';
import {
  advanceRun,
  advanceRunUntil,
  expectCurrentStep,
  guidedPage,
  startRun,
  timerSeconds,
  valueNow,
} from '../../support/guided-page';
import { MockBackend } from '../../support/mock-backend';

test.describe('guided run phases', () => {
  test('starts the warm-up once the setup check passes, with step 2 current and a silent countdown from 60 s', async ({
    page,
  }) => {
    await page.clock.install();
    const backend = await MockBackend.attach(page);
    const guided = guidedPage(page);

    await startRun(page, backend);

    await expect(guided.phaseLine('Step 2 of 4, warm-up')).toBeVisible();
    await expectCurrentStep(page, 'Warm-up');
    await expect(guided.headline('Stay in frame. No need to watch.')).toBeVisible();
    await expect(guided.warmUpTimer).toHaveText(/^\d+ s$/);
    const first = await timerSeconds(guided.warmUpTimer);
    expect(first).toBeGreaterThanOrEqual(55);
    expect(first).toBeLessThanOrEqual(60);
    await expect(guided.warmUpTimer).not.toHaveAttribute('aria-live', /polite|assertive/);
    await expect(guided.stop).toBeVisible();

    await advanceRun(page, backend, 10000);

    expect(await timerSeconds(guided.warmUpTimer)).toBeLessThanOrEqual(first - 9);
  });

  test('fills the warm-up bar and leaves the counted bar empty during the warm-up', async ({ page }) => {
    await page.clock.install();
    const backend = await MockBackend.attach(page);
    const guided = guidedPage(page);
    await startRun(page, backend);

    await advanceRun(page, backend, 12000);

    const warmUp = await valueNow(guided.warmUpBar);
    expect(warmUp).toBeGreaterThanOrEqual(18);
    expect(warmUp).toBeLessThanOrEqual(30);
    await expect(guided.warmUpBar).toHaveAttribute('aria-valuemin', '0');
    await expect(guided.warmUpBar).toHaveAttribute('aria-valuemax', '100');
    await expect(guided.warmUpBar).toHaveAttribute('aria-valuetext', /percent/);
    await expect(guided.main.getByText(`${warmUp}%`, { exact: true })).toBeVisible();
    await expect(guided.countedBar).toHaveAttribute('aria-valuenow', '0');
    await expect(guided.main.getByText('0%', { exact: true })).toBeVisible();
  });

  test('shows the 20 s settle as its own percent bar inside the warm-up while no heart rate is ready', async ({
    page,
  }) => {
    await page.clock.install();
    const backend = await MockBackend.attach(page);
    const guided = guidedPage(page);
    await startRun(page, backend);

    await expect(guided.liveReadings).toContainText(/Settling, \d+%/);
    await expect(guided.settleBar).toBeVisible();
    const before = await valueNow(guided.settleBar);

    await advanceRun(page, backend, 10000, 2500);

    await expect.poll(() => valueNow(guided.settleBar)).toBeGreaterThan(before);
    await expect(guided.liveReadings).toContainText(/Settling, \d+%/);
    await expect(guided.liveReadings.getByText('No value yet', { exact: true })).toBeVisible();
  });

  test('keeps the warm-up for a fixed 60 s, then moves to the counted part', async ({ page }) => {
    await page.clock.install();
    const backend = await MockBackend.attach(page);
    const guided = guidedPage(page);
    await startRun(page, backend);

    await advanceRun(page, backend, 55000);

    await expectCurrentStep(page, 'Warm-up');
    await expect(guided.warmUpTimer).toBeVisible();

    await advanceRun(page, backend, 7000, 1000);

    await expectCurrentStep(page, 'Counted');
    await expect(guided.phaseLine('Step 3 of 4, counted')).toBeVisible();
    await expect(guided.headline('Counting. Hold still.')).toBeVisible();
    await expect(guided.warmUpBar).toHaveAttribute('aria-valuenow', '100');
    await expect(guided.warmUpTimer).toHaveCount(0);
    const left = await timerSeconds(guided.countedTimer);
    expect(left).toBeGreaterThanOrEqual(84);
    expect(left).toBeLessThanOrEqual(90);
    await expect(guided.countedTimer).not.toHaveAttribute('aria-live', /polite|assertive/);
  });

  test('counts for a fixed 90 s with the counted bar filling, then shows the result step', async ({ page }) => {
    await page.clock.install();
    const backend = await MockBackend.attach(page);
    const guided = guidedPage(page);
    await startRun(page, backend);
    await advanceRun(page, backend, 55000);
    await advanceRunUntil(page, backend, guided.countedTimer, 1000);

    await advanceRun(page, backend, 45000);

    const halfway = await valueNow(guided.countedBar);
    expect(halfway).toBeGreaterThanOrEqual(45);
    expect(halfway).toBeLessThanOrEqual(60);
    await expect(guided.main.getByText(`${halfway}%`, { exact: true })).toBeVisible();
    await expect(guided.countedBar).toHaveAttribute('aria-valuetext', /percent/);

    await advanceRun(page, backend, 39000);

    await expectCurrentStep(page, 'Counted');
    await expect(guided.stop).toBeVisible();

    await advanceRun(page, backend, 8000, 1000);

    await expectCurrentStep(page, 'Result');
    await expect(guided.phaseLine('Step 4 of 4, result')).toBeVisible();
    await expect(guided.countedTimer).toHaveCount(0);
    await expect(guided.startAgain).toBeVisible();
    await expect(guided.stop).toHaveCount(0);
  });
});
