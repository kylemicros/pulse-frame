import { expect, test, type Page } from '@playwright/test';
import {
  advanceRun,
  advanceRunUntil,
  advanceStalledRunUntil,
  expectCurrentStep,
  expectQuietRef,
  guidedPage,
  pushAndConfirm,
  setHrvAndConfirm,
  startRun,
  termLines,
} from '../../support/guided-page';
import { hrv, MockBackend, NO_FACE_SCENE, type Hrv } from '../../support/mock-backend';
import { cameraTrackStates, spyOnCamera } from '../../support/page-helpers';

const ok = (bpm: number) => ({ bpm, quality_db: 9.2, state: 'ok' }) as const;

const BEAT_TO_BEAT = 'Beat to beat variation';
const OVERALL = 'Overall rhythm variation';
const NOT_THIS_TIME = 'Not enough beats this time';
const AVERAGE_LINE = 'Average over the last counted minute.';
const LIGHT_ADVICE = 'Face a window so the light is even, hold still, then press Start again.';
const EARLIER_VALUES = hrv({ rmssd_ms: 38.2, sdnn_ms: 44.1, minute_bpm: 71.2, minute_count: 50 });
const NO_READING_LINE =
  'Not enough steady beats came through in the last counted minute. Hold still with your shoulders loose, then press Start again.';

function ms(value: number) {
  return expect.stringMatching(new RegExp(`^${value} ?ms$`));
}

function bpmLine(value: number) {
  return expect.stringMatching(new RegExp(`^${value} ?BPM$`));
}

async function runToEndWithLastMessage(page: Page, backend: MockBackend, last: Hrv): Promise<void> {
  const guided = guidedPage(page);
  await startRun(page, backend);
  await pushAndConfirm(page, backend, ok(80.4));
  await advanceRunUntil(page, backend, guided.countedTimer);
  await setHrvAndConfirm(page, backend, EARLIER_VALUES);
  await advanceRun(page, backend, 60000);
  await setHrvAndConfirm(page, backend, last);
  await advanceRunUntil(page, backend, guided.startAgain);
}

async function expectNoReadingDone(page: Page, lead: string, code: string): Promise<void> {
  const guided = guidedPage(page);
  await expect(guided.headline('Done, but no reading this time.')).toBeVisible();
  await expectCurrentStep(page, 'Result');
  await expect(guided.main.getByText(lead, { exact: true })).toBeVisible();
  await expectQuietRef(guided.main, lead, code);
  await expect(guided.main.getByText(/^Ref: /)).toHaveCount(1);
  await expect.poll(() => termLines(guided.main, 'Heart rate')).toEqual(['No reading this time', 'Last counted minute.']);
  await expect.poll(() => termLines(guided.main, BEAT_TO_BEAT)).toEqual([NOT_THIS_TIME]);
  await expect.poll(() => termLines(guided.main, OVERALL)).toEqual([NOT_THIS_TIME]);
  await expect(guided.variationLine).toHaveCount(0);
  await expect(guided.main.getByRole('definition').filter({ hasText: /\bms\b/ })).toHaveCount(0);
  await expect(guided.alert).toHaveCount(0);
  await expect(guided.startAgain).toBeVisible();
  await expect(guided.milestones).toHaveText(/^Done\. No reading this time\.?$/);
}

const NO_READING_CASES: Array<{ name: string; last: Hrv; lead: string; code: string }> = [
  {
    name: 'the pulse reader says the signal was too weak',
    last: hrv({ no_reading: 'SIGNAL_TOO_WEAK' }),
    lead: `Your pulse never showed clearly enough to count. ${LIGHT_ADVICE}`,
    code: 'SIGNAL_TOO_WEAK',
  },
  {
    name: 'the pulse reader says the face kept leaving the view',
    last: hrv({
      rmssd_ms: 35.2,
      minute_count: 20,
      no_reading: 'READING_FLOOR_NOT_CLEARED',
      why: 'face_left_view',
    }),
    lead: "Your face kept leaving the camera's view, so your pulse couldn't be read. Sit facing the camera and keep your face in view, then press Start again.",
    code: 'READING_FLOOR_NOT_CLEARED',
  },
  {
    name: 'the pulse showed clearly in 18.5% of the counted part',
    last: hrv({ minute_count: 9, no_reading: 'READING_FLOOR_NOT_CLEARED', why: 'faint_pulse', clear_percent: 18.5 }),
    lead: `Your pulse showed clearly in only 19% of the counted part. ${LIGHT_ADVICE}`,
    code: 'READING_FLOOR_NOT_CLEARED',
  },
  {
    name: 'the pulse showed clearly in 0.5% of the counted part',
    last: hrv({ minute_count: 1, no_reading: 'READING_FLOOR_NOT_CLEARED', why: 'faint_pulse', clear_percent: 0.5 }),
    lead: `Your pulse showed clearly in only 1% of the counted part. ${LIGHT_ADVICE}`,
    code: 'READING_FLOOR_NOT_CLEARED',
  },
  {
    name: 'the pulse showed clearly in 0.4% of the counted part',
    last: hrv({ minute_count: 1, no_reading: 'READING_FLOOR_NOT_CLEARED', why: 'faint_pulse', clear_percent: 0.4 }),
    lead: `Your pulse showed clearly in under 1% of the counted part. ${LIGHT_ADVICE}`,
    code: 'READING_FLOOR_NOT_CLEARED',
  },
  {
    name: 'the pulse never showed clearly during the counted part',
    last: hrv({ no_reading: 'READING_FLOOR_NOT_CLEARED', why: 'faint_pulse', clear_percent: 0 }),
    lead: `Your pulse never showed clearly during the counted part. ${LIGHT_ADVICE}`,
    code: 'READING_FLOOR_NOT_CLEARED',
  },
  {
    name: 'the pulse reader gives no heart rate and no reason',
    last: hrv({ rmssd_ms: 33.6, sdnn_ms: 40.2, minute_count: 30 }),
    lead: NO_READING_LINE,
    code: 'NO_READING',
  },
];

test.describe('guided run result', () => {
  test("shows the pulse reader's last minute heart rate and variation, rounded half up, then turns the camera off", async ({
    page,
  }) => {
    await spyOnCamera(page);
    await page.clock.install();
    const backend = await MockBackend.attach(page);
    const guided = guidedPage(page);

    await runToEndWithLastMessage(
      page,
      backend,
      hrv({ rmssd_ms: 41.2, sdnn_ms: 46.5, minute_bpm: 68.5, minute_count: 72, bpm_low: null, bpm_high: null }),
    );

    await expect(guided.headline('Done. Nice sitting.')).toBeVisible();
    await expectCurrentStep(page, 'Result');
    const result = guided.main.getByRole('definition').filter({ hasText: 'BPM' });
    await expect(result).toHaveText(/^\s*69\s*BPM\s*$/);
    await expect.poll(() => termLines(guided.main, 'Heart rate')).toEqual([bpmLine(69), AVERAGE_LINE]);
    await expect.poll(() => termLines(guided.main, BEAT_TO_BEAT)).toEqual([ms(41), 'Over the whole counted part.']);
    await expect.poll(() => termLines(guided.main, OVERALL)).toEqual([ms(47), 'Last counted minute.']);
    await expect(guided.variationLine).toBeVisible();
    await expect(guided.main).not.toContainText(/likely|baseline/i);
    await expect(guided.main).not.toContainText(/RMSSD|SDNN/);
    await expect(guided.main).not.toContainText(/\b80(\.4)?\b/);
    await expect(guided.main.getByText(/Checking against a watch\?/)).toBeVisible();
    await expect(guided.main.getByText("Camera's off. Run finished.")).toBeVisible();
    await expect(guided.main.getByText(/^Ref: /)).toHaveCount(0);
    await expect(guided.disclaimer).toBeVisible();
    await expect(guided.milestones).toHaveText(
      'Done. Heart rate 69 beats per minute. Beat to beat variation 41 milliseconds. Overall rhythm variation 47 milliseconds.',
    );
    await expect.poll(() => cameraTrackStates(page)).toEqual(expect.arrayContaining(['ended']));
    expect((await cameraTrackStates(page)).every((state) => state === 'ended')).toBe(true);
    await expect.poll(() => backend.openConnections().length).toBe(0);
  });

  test('says "Not enough beats this time" on a variation tile with no value when the result has a heart rate', async ({
    page,
  }) => {
    await page.clock.install();
    const backend = await MockBackend.attach(page);
    const guided = guidedPage(page);

    await runToEndWithLastMessage(page, backend, hrv({ rmssd_ms: 35.5, minute_bpm: 70.2, minute_count: 48 }));

    await expect(guided.headline('Done. Nice sitting.')).toBeVisible();
    await expect.poll(() => termLines(guided.main, 'Heart rate')).toEqual([bpmLine(70), AVERAGE_LINE]);
    await expect.poll(() => termLines(guided.main, BEAT_TO_BEAT)).toEqual([ms(36), 'Over the whole counted part.']);
    await expect.poll(() => termLines(guided.main, OVERALL)).toEqual([NOT_THIS_TIME, 'Last counted minute.']);
    await expect(guided.variationLine).toBeVisible();
    await expect(guided.milestones).toHaveText(
      'Done. Heart rate 70 beats per minute. Beat to beat variation 36 milliseconds.',
    );
  });

  test('shows the heart rate with "Not enough beats this time" on both tiles when the last message has a heart rate but no variation', async ({
    page,
  }) => {
    await page.clock.install();
    const backend = await MockBackend.attach(page);
    const guided = guidedPage(page);

    await runToEndWithLastMessage(page, backend, hrv({ minute_bpm: 67.4, minute_count: 46 }));

    await expect(guided.headline('Done. Nice sitting.')).toBeVisible();
    await expect.poll(() => termLines(guided.main, 'Heart rate')).toEqual([bpmLine(67), AVERAGE_LINE]);
    await expect.poll(() => termLines(guided.main, BEAT_TO_BEAT)).toEqual([NOT_THIS_TIME, 'Over the whole counted part.']);
    await expect.poll(() => termLines(guided.main, OVERALL)).toEqual([NOT_THIS_TIME, 'Last counted minute.']);
    await expect(guided.main.getByText(/^Ref: /)).toHaveCount(0);
    await expect(guided.main).not.toContainText(/\b(38|44)\b/);
    await expect(guided.milestones).toHaveText('Done. Heart rate 67 beats per minute.');
  });

  test("takes the heart rate from the pulse reader even when the page's own view saw no face while counting", async ({
    page,
  }) => {
    await page.clock.install();
    const backend = await MockBackend.attach(page);
    const guided = guidedPage(page);
    await startRun(page, backend);
    await advanceRunUntil(page, backend, guided.countedTimer);

    backend.setScene(NO_FACE_SCENE);
    await setHrvAndConfirm(page, backend, hrv({ rmssd_ms: 30.1, sdnn_ms: 39.8, minute_bpm: 64.6, minute_count: 66 }));
    await advanceRunUntil(page, backend, guided.startAgain);

    await expect(guided.headline('Done. Nice sitting.')).toBeVisible();
    await expect.poll(() => termLines(guided.main, 'Heart rate')).toEqual([bpmLine(65), AVERAGE_LINE]);
    await expect(guided.main).not.toContainText(/kept leaving/);
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

  for (const { name, last, lead, code } of NO_READING_CASES) {
    test(`ends with no reading and Ref: ${code} when ${name}`, async ({ page }) => {
      await page.clock.install();
      const backend = await MockBackend.attach(page);

      await runToEndWithLastMessage(page, backend, last);

      await expectNoReadingDone(page, lead, code);
      await expect(guidedPage(page).main).not.toContainText(/\b(80|71|38|44)\b/);
    });
  }

  test('ends with no reading and Ref: NO_READING when no hrv message came before the end', async ({ page }) => {
    await page.clock.install();
    const backend = await MockBackend.attach(page);
    const guided = guidedPage(page);
    await startRun(page, backend);
    await pushAndConfirm(page, backend, ok(70.5));
    await advanceRun(page, backend, 65000);
    await pushAndConfirm(page, backend, ok(69.5));

    await advanceRunUntil(page, backend, guided.startAgain);

    await expectNoReadingDone(page, NO_READING_LINE, 'NO_READING');
    await expect(guided.main).not.toContainText(/\b(69|70)(\.5)?\b/);
  });

  test('shows nothing of a no reading code that arrives mid-run and goes by the last message at the end', async ({
    page,
  }) => {
    await page.clock.install();
    const backend = await MockBackend.attach(page);
    const guided = guidedPage(page);
    await startRun(page, backend);
    await advanceRunUntil(page, backend, guided.countedTimer);

    await setHrvAndConfirm(page, backend, hrv({ no_reading: 'SIGNAL_TOO_WEAK' }));
    await advanceRun(page, backend, 3000, 500);

    await expect(guided.headline('Counting. Hold still.')).toBeVisible();
    await expect(guided.main.getByText(/SIGNAL_TOO_WEAK|never showed clearly/)).toHaveCount(0);
    await expect(guided.main.getByText(/^Ref: /)).toHaveCount(0);
    await expect(guided.alert).toHaveCount(0);

    await setHrvAndConfirm(
      page,
      backend,
      hrv({ no_reading: 'READING_FLOOR_NOT_CLEARED', why: 'faint_pulse', clear_percent: 12.2, minute_count: 5 }),
    );
    await advanceRun(page, backend, 3000, 500);

    await expect(guided.main.getByText(/READING_FLOOR_NOT_CLEARED|showed clearly in/)).toHaveCount(0);
    await expect(guided.main.getByText(/^Ref: /)).toHaveCount(0);

    await setHrvAndConfirm(page, backend, hrv({ rmssd_ms: 44.4, sdnn_ms: 51.6, minute_bpm: 66.4, minute_count: 70 }));
    await advanceRunUntil(page, backend, guided.startAgain);

    await expect(guided.headline('Done. Nice sitting.')).toBeVisible();
    await expect.poll(() => termLines(guided.main, 'Heart rate')).toEqual([bpmLine(66), AVERAGE_LINE]);
    await expect(guided.main.getByText(/^Ref: /)).toHaveCount(0);
  });

  const stalls = [
    { how: 'stops replying with the socket open', stall: (backend: MockBackend) => backend.holdReplies() },
    {
      how: 'sends one unreadable reply and then goes quiet with the socket open',
      stall: (backend: MockBackend) => backend.sendUnreadableNext('{not json', { holdAfter: true }),
    },
  ] as const;

  test('ends with no reading, never the last minute heart rate, when the pulse reader stalls after sending one', async ({
    page,
  }) => {
    await page.clock.install();
    const backend = await MockBackend.attach(page);
    const guided = guidedPage(page);
    await startRun(page, backend);
    await advanceRunUntil(page, backend, guided.countedTimer);
    await advanceRun(page, backend, 50000);
    await setHrvAndConfirm(page, backend, hrv({ rmssd_ms: 41.2, sdnn_ms: 46.5, minute_bpm: 72.6, minute_count: 70 }));
    await advanceRun(page, backend, 2000, 500);

    backend.holdReplies();
    await advanceStalledRunUntil(page, guided.startAgain);

    await expectNoReadingDone(page, NO_READING_LINE, 'NO_READING');
    await expect(guided.main.getByRole('definition').filter({ hasText: 'BPM' })).toHaveCount(0);
    await expect(guided.main).not.toContainText(/\b(73|72(\.6)?|41|47)\b/);
    await expect(guided.milestones).not.toContainText(/\b73\b/);
    await expect.poll(() => backend.openConnections().length).toBe(0);
  });

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

      await expectNoReadingDone(page, NO_READING_LINE, 'NO_READING');
      await expect(guided.main.getByRole('definition').filter({ hasText: 'BPM' })).toHaveCount(0);
      await expect(guided.milestones).not.toContainText(/\b70\b/);
      await expect.poll(() => backend.openConnections().length).toBe(0);
    });
  }
});
