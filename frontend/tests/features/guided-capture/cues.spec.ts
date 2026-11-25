import { expect, test, type Page } from '@playwright/test';
import {
  advanceRun,
  advanceRunUntil,
  audioContextsClosed,
  breakAudioContext,
  expectCurrentStep,
  guidedPage,
  openGuidedRun,
  pushAndConfirm,
  soundsPlayed,
  spyOnAudioClose,
  spyOnSounds,
  startRun,
} from '../../support/guided-page';
import { hrv, MockBackend } from '../../support/mock-backend';
import { pageNow, refuseCamera, watchedText, watchText } from '../../support/page-helpers';

const MILESTONES = [
  /^Warm-up started\b/,
  /^Counting starts in 10 seconds\b/,
  /^Counting started\b/,
  /halfway/i,
  /^10 seconds left\b/,
  /^Done\. Heart rate 68 beats per minute\b/,
];

const MILESTONE_AT_MS = [0, 50000, 60000, 105000, 140000, 150000];
const SLICE_MS = 2500;

async function runWithSteadyReadings(page: Page, backend: MockBackend): Promise<void> {
  const guided = guidedPage(page);
  backend.setHrv(hrv({ rmssd_ms: 40.2, sdnn_ms: 45.1, minute_bpm: 68.2, minute_count: 70 }));
  await pushAndConfirm(page, backend, { bpm: 68.2, quality_db: 9.4, state: 'ok' });
  await advanceRun(page, backend, 70000, SLICE_MS);
  await pushAndConfirm(page, backend, { bpm: 67.8, quality_db: 9.4, state: 'ok' });
  await advanceRun(page, backend, 40000, SLICE_MS);
  await pushAndConfirm(page, backend, { bpm: 68.2, quality_db: 9.4, state: 'ok' });
  await advanceRunUntil(page, backend, guided.startAgain, SLICE_MS);
}

test.describe('guided run cues', () => {
  test('speaks through one polite status only at the six milestones, never the live values', async ({ page }) => {
    await page.clock.install();
    const backend = await MockBackend.attach(page);
    const guided = guidedPage(page);
    await openGuidedRun(page);
    await expect(guided.milestones).toBeAttached();
    await expect(guided.milestones).toHaveRole('status');
    await expect(guided.milestones).not.toHaveAttribute('aria-live', 'assertive');
    await watchText(guided.milestones, 'milestones');

    await guided.start.click();
    const startedAt = await pageNow(page);
    await expect.poll(() => backend.frames.length).toBeGreaterThan(1);
    await runWithSteadyReadings(page, backend);
    await expect(guided.milestones).toHaveText(MILESTONES[5]);

    const spoken = (await watchedText(page, 'milestones')).filter((change) => change.text.trim() !== '');
    expect(spoken.map((change) => change.text.trim())).toEqual(MILESTONES.map((pattern) => expect.stringMatching(pattern)));
    for (const [index, change] of spoken.entries()) {
      expect(Math.abs(change.at - startedAt - MILESTONE_AT_MS[index])).toBeLessThanOrEqual(SLICE_MS + 2000);
    }
    await expect(page.getByRole('status').filter({ hasText: MILESTONES[5] })).toHaveCount(1);
  });

  test('changes the tab title, headline and steps at each phase', async ({ page }) => {
    await page.clock.install();
    const backend = await MockBackend.attach(page);
    const guided = guidedPage(page);
    await openGuidedRun(page);
    await guided.start.click();

    await expect(page).toHaveTitle(/^Warm-up, \d+ s\b/);
    await expect(guided.headline('Stay in frame. No need to watch.')).toBeVisible();
    await expectCurrentStep(page, 'Warm-up');

    await advanceRunUntil(page, backend, guided.countedTimer);

    await expect(page).toHaveTitle(/^Counting, \d+ s\b/);
    await expect(guided.headline('Counting. Hold still.')).toBeVisible();
    await expectCurrentStep(page, 'Counted');

    await advanceRunUntil(page, backend, guided.startAgain);

    await expect(page).toHaveTitle(/^Done\b/);
    await expectCurrentStep(page, 'Result');
  });

  test('plays the chime when counting starts and when the run is done while the chime is on', async ({ page }) => {
    await spyOnSounds(page);
    await page.clock.install();
    const backend = await MockBackend.attach(page);
    const guided = guidedPage(page);
    await openGuidedRun(page);
    await expect(guided.chime).toHaveAttribute('aria-pressed', 'true');
    await guided.start.click();
    await expect.poll(() => backend.frames.length).toBeGreaterThan(1);
    const duringWarmUp = await soundsPlayed(page);

    await advanceRunUntil(page, backend, guided.countedTimer, 1000);
    await expect.poll(() => soundsPlayed(page)).toBeGreaterThan(duringWarmUp);
    const duringCounting = await soundsPlayed(page);

    await advanceRunUntil(page, backend, guided.startAgain);
    await expect.poll(() => soundsPlayed(page)).toBeGreaterThan(duringCounting);
  });

  test('closes the chime audio once when the run is done', async ({ page }) => {
    await spyOnAudioClose(page);
    await page.clock.install();
    const backend = await MockBackend.attach(page);
    const guided = guidedPage(page);
    await startRun(page, backend);

    await advanceRunUntil(page, backend, guided.startAgain);

    await expect(guided.headline('Done, but no reading this time.')).toBeVisible();
    await expect.poll(() => audioContextsClosed(page)).toBe(1);
  });

  test('closes the chime audio once when Stop is pressed', async ({ page }) => {
    await spyOnAudioClose(page);
    await page.clock.install();
    const backend = await MockBackend.attach(page);
    const guided = guidedPage(page);
    await startRun(page, backend);
    await advanceRun(page, backend, 10000);

    await guided.stop.click();

    await expect(guided.startAgain).toBeVisible();
    await expect.poll(() => audioContextsClosed(page)).toBe(1);
  });

  test('closes the chime audio once when the camera is refused at Start', async ({ page }) => {
    await spyOnAudioClose(page);
    await refuseCamera(page, 'NotAllowedError');
    await MockBackend.attach(page);
    const guided = guidedPage(page);
    await openGuidedRun(page);
    await expect(guided.chime).toHaveAttribute('aria-pressed', 'true');

    await guided.start.click();

    await expect(guided.alert).toContainText('Ref: CAMERA_DENIED');
    await expect.poll(() => audioContextsClosed(page)).toBe(1);
  });

  test('closes the chime audio once when the page is hidden for good mid-run', async ({ page }) => {
    await spyOnAudioClose(page);
    await page.clock.install();
    const backend = await MockBackend.attach(page);
    await startRun(page, backend);
    await advanceRun(page, backend, 10000);

    await page.evaluate(() => globalThis.dispatchEvent(new PageTransitionEvent('pagehide', { persisted: false })));

    await expect.poll(() => backend.openConnections().length).toBe(0);
    await expect.poll(() => audioContextsClosed(page)).toBe(1);
  });

  test('reaches Done with every phase change on screen and in the title, and no alert, when the browser cannot make a chime', async ({
    page,
  }) => {
    await breakAudioContext(page);
    const pageErrors: string[] = [];
    page.on('pageerror', (error) => pageErrors.push(error.message));
    await page.clock.install();
    const backend = await MockBackend.attach(page);
    const guided = guidedPage(page);
    await openGuidedRun(page);
    await expect(guided.chime).toHaveAttribute('aria-pressed', 'true');
    await watchText(guided.milestones, 'milestones');

    await guided.start.click();
    await expect(page).toHaveTitle(/^Warm-up, \d+ s\b/);
    await expect(guided.headline('Stay in frame. No need to watch.')).toBeVisible();
    await expectCurrentStep(page, 'Warm-up');
    await advanceRunUntil(page, backend, guided.countedTimer);
    await expect(page).toHaveTitle(/^Counting, \d+ s\b/);
    await expect(guided.headline('Counting. Hold still.')).toBeVisible();
    await expectCurrentStep(page, 'Counted');
    await advanceRunUntil(page, backend, guided.startAgain);

    await expect(page).toHaveTitle(/^Done\b/);
    await expectCurrentStep(page, 'Result');
    await expect(guided.alert).toHaveCount(0);
    await expect(guided.main).not.toContainText(/Ref: (?!NO_READING)/);
    const spoken = (await watchedText(page, 'milestones')).map((change) => change.text);
    expect(spoken).toContainEqual(expect.stringMatching(/^Counting started\b/));
    expect(spoken).toContainEqual(expect.stringMatching(/^Done\b/));
    expect(pageErrors).toEqual([]);
  });

  test('plays no chime when it is off, and every phase change still shows on screen and in the title', async ({
    page,
  }) => {
    await spyOnSounds(page);
    await page.clock.install();
    const backend = await MockBackend.attach(page);
    const guided = guidedPage(page);
    await openGuidedRun(page);
    await guided.chime.click();
    await expect(guided.chime).toHaveAttribute('aria-pressed', 'false');
    await watchText(guided.milestones, 'milestones');

    await guided.start.click();
    await expect(page).toHaveTitle(/^Warm-up, \d+ s\b/);
    await advanceRunUntil(page, backend, guided.countedTimer);
    await expect(page).toHaveTitle(/^Counting, \d+ s\b/);
    await expect(guided.headline('Counting. Hold still.')).toBeVisible();
    await advanceRunUntil(page, backend, guided.startAgain);

    await expect(page).toHaveTitle(/^Done\b/);
    await expectCurrentStep(page, 'Result');
    const spoken = (await watchedText(page, 'milestones')).map((change) => change.text);
    expect(spoken).toContainEqual(expect.stringMatching(/^Counting started\b/));
    expect(spoken).toContainEqual(expect.stringMatching(/^Done\b/));
    expect(await soundsPlayed(page)).toBe(0);
  });
});
