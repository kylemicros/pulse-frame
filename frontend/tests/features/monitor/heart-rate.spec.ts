import { expect, test } from '@playwright/test';
import { faceScene, MockBackend, NO_FACE_SCENE } from '../../support/mock-backend';
import {
  monitorPage,
  pageNow,
  settleRendering,
  startMonitoring,
  waitForMoreFrames,
  watchedText,
  watchText,
} from '../../support/monitor-page';
import { firstMessageAfter, socketRecords } from '../../support/socket-recorder';

const OK_READING = { bpm: 74.6, quality_db: 5.21, state: 'ok' } as const;
const LOW_QUALITY_READING = { bpm: null, quality_db: null, state: 'low_quality' } as const;
const SHOWN_BPM = /^(74\.6|75)$/;
const DASH = /^-+$/;

function settlingSeconds(text: string): number | null {
  const match = /Settling (\d+) s/.exec(text);
  return match === null ? null : Number(match[1]);
}

test.describe('heart rate', () => {
  test('counts down while settling and shows no number', async ({ page }) => {
    const backend = await MockBackend.attach(page);
    const monitor = monitorPage(page);

    await startMonitoring(page, backend);

    await expect(monitor.heartRate).toContainText(/Settling \d+ s/);
    await expect(monitor.bpmValue).not.toHaveText(/^\d+(\.\d+)?$/);
    const first = settlingSeconds(await monitor.heartRate.innerText());
    expect(first).not.toBeNull();
    expect(first).toBeGreaterThanOrEqual(1);
    expect(first).toBeLessThanOrEqual(20);
    await expect
      .poll(async () => settlingSeconds(await monitor.heartRate.innerText()))
      .toBeLessThan(first ?? 0);
  });

  test('shows the BPM number when the reading is ok', async ({ page }) => {
    const backend = await MockBackend.attach(page);
    const monitor = monitorPage(page);
    await startMonitoring(page, backend);

    backend.pushReading(OK_READING);

    await expect(monitor.bpmValue).toHaveText(SHOWN_BPM);
    await expect(monitor.heartRate).not.toContainText(/Settling/);
  });

  test('keeps the last BPM dimmed for 400 ms after the reading leaves ok, then shows a dash', async ({ page }) => {
    const backend = await MockBackend.attach(page);
    const monitor = monitorPage(page);
    await startMonitoring(page, backend);
    backend.pushReading(OK_READING);
    await expect(monitor.bpmValue).toHaveText(SHOWN_BPM);
    await watchText(monitor.bpmValue, 'bpm');
    const watchedFrom = await pageNow(page);

    backend.pushReading({ bpm: null, quality_db: 1.2, state: 'low_quality' });

    await expect
      .poll(
        async () => ({
          text: await monitor.bpmValue.innerText(),
          dimmed: await monitor.bpmValue.evaluate((element) => Number(getComputedStyle(element).opacity) < 1),
        }),
        { intervals: [20] },
      )
      .toEqual({ text: expect.stringMatching(SHOWN_BPM), dimmed: true });
    await expect(monitor.bpmValue).toHaveText(DASH);

    const leftOk = firstMessageAfter(
      await socketRecords(page),
      watchedFrom,
      (message) => message.type === 'bpm' && message.state !== 'ok',
    );
    const changes = await watchedText(page, 'bpm');
    expect(leftOk).not.toBeNull();
    expect(changes.map((change) => change.text)).toEqual([
      expect.stringMatching(SHOWN_BPM),
      expect.stringMatching(DASH),
    ]);
    const heldMs = changes[1].at - (leftOk?.at ?? Number.NaN);
    expect(heldMs).toBeGreaterThanOrEqual(380);
    expect(heldMs).toBeLessThanOrEqual(700);
  });

  test('shows a dash and asks to hold still while the user moves', async ({ page }) => {
    const backend = await MockBackend.attach(page);
    const monitor = monitorPage(page);
    await startMonitoring(page, backend);

    backend.setScene(faceScene({ moving: true }));
    backend.pushReading(LOW_QUALITY_READING);

    await expect(monitor.bpmValue).toHaveText(DASH);
    await expect(monitor.heartRate).toContainText(/hold still/i);
  });

  test('shows a dash and says no face when no face is found', async ({ page }) => {
    const backend = await MockBackend.attach(page);
    const monitor = monitorPage(page);
    await startMonitoring(page, backend);

    backend.setScene(NO_FACE_SCENE);
    backend.pushReading(LOW_QUALITY_READING);

    await expect(monitor.bpmValue).toHaveText(DASH);
    await expect(monitor.heartRate).toContainText(/no face/i);
  });

  test('shows a dash and a lighting hint when a still face gives a low quality reading', async ({ page }) => {
    const backend = await MockBackend.attach(page);
    const monitor = monitorPage(page);
    await startMonitoring(page, backend);

    backend.pushReading({ bpm: null, quality_db: 1.2, state: 'low_quality' });

    await expect(monitor.bpmValue).toHaveText(DASH);
    await expect(monitor.heartRate).toContainText(/light/i);
    await expect(monitor.heartRate).not.toContainText(/hold still|no face/i);
  });

  test('holds the shown reason for at least 400 ms when the user moves for a single frame', async ({ page }) => {
    const backend = await MockBackend.attach(page);
    const monitor = monitorPage(page);
    await startMonitoring(page, backend);
    backend.pushReading({ bpm: null, quality_db: 1.2, state: 'low_quality' });
    await expect(monitor.heartRate).toContainText(/light/i);
    await watchText(monitor.heartRate, 'reason');

    backend.flashScene(faceScene({ moving: true }));

    await expect.poll(() => backend.flashedAtFrames.length).toBe(1);
    await waitForMoreFrames(backend, 20);
    await settleRendering(page);

    const changes = await watchedText(page, 'reason');
    const gaps = changes.slice(1).map((change, index) => change.at - changes[index].at);
    expect(gaps.slice(1).filter((gap) => gap < 380)).toEqual([]);
    await expect(monitor.heartRate).toContainText(/light/i);
  });
});
