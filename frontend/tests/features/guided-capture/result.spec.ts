import { expect, test, type Page } from '@playwright/test';
import {
  advanceRun,
  advanceRunUntil,
  advanceStalledRunUntil,
  expectCurrentStep,
  guidedPage,
  pushAndConfirm,
  startRun,
} from '../../support/guided-page';
import { MockBackend, NO_FACE_SCENE } from '../../support/mock-backend';
import { cameraTrackStates, CODED_ALERT_TEXT, spyOnCamera } from '../../support/monitor-page';

const ok = (bpm: number) => ({ bpm, quality_db: 9.2, state: 'ok' }) as const;
const LOW_QUALITY = { bpm: null, quality_db: 1.2, state: 'low_quality' } as const;

async function expectNoReadingDone(page: Page, reason: string, whatToDo: string): Promise<void> {
  const guided = guidedPage(page);
  await expect(guided.headline('Done, but no reading this time.')).toBeVisible();
  await expectCurrentStep(page, 'Result');
  await expect(guided.panel.getByText(reason)).toBeVisible();
  await expect(guided.panel.getByText(whatToDo)).toBeVisible();
  await expect(guided.panel.getByText('No reading this time', { exact: true })).toBeVisible();
  await expect(guided.panel.getByText('Ref: NO_READING', { exact: true })).toBeVisible();
  await expect(guided.alert).toHaveCount(0);
  await expect(guided.notEnoughBeats).toHaveCount(2);
  await expect(guided.startAgain).toBeVisible();
  await expect(guided.milestones).toHaveText(/^Done\. No reading this time\b/);
  const reasonText = await guided.panel.getByText(reason).innerText();
  expect(reasonText).not.toMatch(CODED_ALERT_TEXT);
}

test.describe('guided run result', () => {
  test('shows the average heart rate over the last counted minute only, then turns the camera off', async ({
    page,
  }) => {
    await spyOnCamera(page);
    await page.clock.install();
    const backend = await MockBackend.attach(page);
    const guided = guidedPage(page);
    await startRun(page, backend);

    await pushAndConfirm(page, backend, ok(96));
    await advanceRun(page, backend, 65000);
    await pushAndConfirm(page, backend, ok(80));
    await advanceRun(page, backend, 20000);
    await pushAndConfirm(page, backend, ok(68.4));
    await advanceRun(page, backend, 15000);
    await pushAndConfirm(page, backend, ok(67.6));
    await advanceRun(page, backend, 20000);
    await pushAndConfirm(page, backend, ok(68.4));
    await advanceRun(page, backend, 20000);
    await pushAndConfirm(page, backend, ok(67.6));
    await advanceRunUntil(page, backend, guided.startAgain);

    await expect(guided.headline('Done. Nice sitting.')).toBeVisible();
    await expectCurrentStep(page, 'Result');
    const result = guided.panel.getByRole('definition').filter({ hasText: 'BPM' });
    await expect(result).toHaveText(/^\s*68\s*BPM\s*$/);
    await expect(guided.panel.getByText('Average over the last counted minute.', { exact: true })).toBeVisible();
    await expect(guided.panel).not.toContainText(/likely|baseline/i);
    await expect(guided.notEnoughBeats).toHaveCount(2);
    await expect(guided.variationLater).toBeVisible();
    await expect(guided.panel.getByText(/Checking against a watch\?/)).toBeVisible();
    await expect(guided.panel.getByText("Camera's off. Run finished.")).toBeVisible();
    await expect(guided.disclaimer).toBeVisible();
    await expect(guided.milestones).toHaveText(/^Done\. Heart rate 68 beats per minute\b/);
    await expect.poll(() => cameraTrackStates(page)).toEqual(expect.arrayContaining(['ended']));
    expect((await cameraTrackStates(page)).every((state) => state === 'ended')).toBe(true);
    await expect.poll(() => backend.openConnections().length).toBe(0);
  });

  test('starts a fresh warm-up when Start again is pressed after a result', async ({ page }) => {
    await page.clock.install();
    const backend = await MockBackend.attach(page);
    const guided = guidedPage(page);
    await startRun(page, backend);
    await advanceRunUntil(page, backend, guided.startAgain);

    await guided.startAgain.click();

    await expectCurrentStep(page, 'Warm-up');
    await expect(guided.headline('Stay in frame. No need to watch.')).toBeVisible();
    await expect.poll(() => backend.openConnections().length).toBe(1);
  });

  test('says plainly that the pulse never showed when no heart rate came in the last counted minute', async ({
    page,
  }) => {
    await page.clock.install();
    const backend = await MockBackend.attach(page);
    const guided = guidedPage(page);
    await startRun(page, backend);

    await advanceRunUntil(page, backend, guided.startAgain);

    await expectNoReadingDone(
      page,
      'Your pulse never showed clearly enough to count.',
      'Face a window so the light is even, hold still, then press Start again.',
    );
  });

  test('says there was no reading when heart rates came only before the last counted minute', async ({ page }) => {
    await page.clock.install();
    const backend = await MockBackend.attach(page);
    const guided = guidedPage(page);
    await startRun(page, backend);
    await pushAndConfirm(page, backend, ok(70.5));
    await advanceRun(page, backend, 65000);

    await pushAndConfirm(page, backend, LOW_QUALITY);
    await advanceRunUntil(page, backend, guided.startAgain);

    await expectNoReadingDone(
      page,
      'Your pulse never showed clearly enough to count.',
      'Face a window so the light is even, hold still, then press Start again.',
    );
    await expect(guided.panel).not.toContainText(/\b70(\.5)?\b/);
  });

  const stalls = [
    { how: 'stops replying with the socket open', stall: (backend: MockBackend) => backend.holdReplies() },
    {
      how: 'sends one unreadable reply and then goes quiet with the socket open',
      stall: (backend: MockBackend) => backend.sendUnreadableNext('{not json', { holdAfter: true }),
    },
  ] as const;

  for (const { how, stall } of stalls) {
    test(`ends with no reading, never the frozen heart rate, when the pulse reader ${how}`, async ({ page }) => {
      await page.clock.install();
      const backend = await MockBackend.attach(page);
      const guided = guidedPage(page);
      await startRun(page, backend);
      await advanceRunUntil(page, backend, guided.countedTimer);
      await pushAndConfirm(page, backend, ok(70.2));
      await expect(guided.liveReadings.getByText(/^70(\.2)?$/)).toBeVisible();

      stall(backend);
      await advanceStalledRunUntil(page, guided.startAgain);

      await expectNoReadingDone(
        page,
        'Your pulse never showed clearly enough to count.',
        'Face a window so the light is even, hold still, then press Start again.',
      );
      await expect(guided.panel.getByRole('definition').filter({ hasText: 'BPM' })).toHaveCount(0);
      await expect(guided.milestones).not.toContainText(/\b70\b/);
      await expect.poll(() => backend.openConnections().length).toBe(0);
    });
  }

  test('says the face kept leaving the view when no face was seen through the counted part', async ({ page }) => {
    await page.clock.install();
    const backend = await MockBackend.attach(page);
    const guided = guidedPage(page);
    await startRun(page, backend);
    await advanceRunUntil(page, backend, guided.countedTimer);

    backend.setScene(NO_FACE_SCENE);
    await advanceRunUntil(page, backend, guided.startAgain, 2500);

    await expectNoReadingDone(
      page,
      "Your face kept leaving the camera's view.",
      'Sit facing the camera and keep your face in view, then press Start again.',
    );
  });
});
