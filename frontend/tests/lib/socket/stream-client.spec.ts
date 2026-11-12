import { expect, test, type Locator } from '@playwright/test';
import { MockBackend, WIRE_ERRORS } from '../../support/mock-backend';
import {
  advanceClockUntil,
  monitorPage,
  ownTextLength,
  settleRendering,
  startMonitoring,
  waitForMoreFrames,
  watchedText,
  watchText,
} from '../../support/monitor-page';
import { retryGaps, socketRecords } from '../../support/socket-recorder';

const ANOTHER_CONNECTION_OPEN = { code: 1013, reason: 'ANOTHER_CONNECTION_OPEN' };
const DROPPED = { code: 1006 };
const PAST_ANY_BACKOFF_MS = 20000;

function gapsBetween(times: number[]): number[] {
  return times.slice(1).map((time, index) => time - times[index]);
}

async function expectMessageAndAction(alert: Locator, code: string): Promise<void> {
  const text = await alert.innerText();
  expect(text.replace(code, '').trim().length).toBeGreaterThan(40);
}

test.describe('stream socket client', () => {
  test('keeps exactly one connection open while monitoring', async ({ page }) => {
    const backend = await MockBackend.attach(page);

    await startMonitoring(page, backend);
    await waitForMoreFrames(backend, 5);

    const open = backend.openConnections();
    expect(open).toHaveLength(1);
    expect(backend.framesOn(open[0].id).length).toBeGreaterThanOrEqual(5);
  });

  test('waits for the turn reply before sending the next frame', async ({ page }) => {
    const backend = await MockBackend.attach(page);
    backend.setReplyDelay(250);

    await startMonitoring(page, backend);
    await waitForMoreFrames(backend, 4);

    expect(backend.frames.filter((frame) => frame.arrivedWhileAwaitingReply)).toEqual([]);
  });

  test('spaces frame sends at least 34 ms apart', async ({ page }) => {
    const backend = await MockBackend.attach(page);

    await startMonitoring(page, backend);
    await waitForMoreFrames(backend, 25);

    const [streaming] = backend.openConnections();
    const frames = backend.framesOn(streaming.id);
    const captureGaps = gapsBetween(frames.map((frame) => frame.captureMs));
    const arrivalGaps = gapsBetween(frames.map((frame) => frame.arrivedAt));
    expect(Math.min(...captureGaps)).toBeGreaterThanOrEqual(34);
    expect(Math.min(...arrivalGaps)).toBeGreaterThanOrEqual(25);
  });

  test('retries with growing delays while another connection holds the backend', async ({ page }) => {
    await page.clock.install();
    const backend = await MockBackend.attach(page);
    backend.refuseEveryConnection(ANOTHER_CONNECTION_OPEN);
    const monitor = monitorPage(page);

    await page.goto('/');
    await monitor.start.click();
    await advanceClockUntil(page, () => backend.connections.length >= 6);

    const records = (await socketRecords(page)).slice(0, 6);
    expect(records.map((record) => record.openedAt !== null)).toEqual([true, true, true, true, true, true]);
    expect(records.slice(0, 5).map((record) => record.closeCode)).toEqual([1013, 1013, 1013, 1013, 1013]);
    const gaps = retryGaps(records);
    expect(gaps[0]).toBeGreaterThanOrEqual(100);
    expect(gaps[4]).toBeGreaterThanOrEqual(3 * gaps[1]);

    backend.acceptEveryConnection();

    await advanceClockUntil(page, () => backend.openConnections().length === 1);
    await waitForMoreFrames(backend, 3);
  });

  test('shows SOCKET_UNAVAILABLE when the backend is not reachable and retries with growing delays', async ({
    page,
  }) => {
    await page.clock.install();
    const backend = await MockBackend.attach(page);
    backend.refuseEveryConnection(DROPPED);
    const monitor = monitorPage(page);

    await page.goto('/');
    await monitor.start.click();

    const alert = monitor.alertWith('SOCKET_UNAVAILABLE');
    await expect(alert).toBeVisible();
    await expect(alert).toContainText(/backend/i);
    await expect(alert).toContainText(/not running|not reachable|cannot reach|can't reach|could not reach/i);

    await advanceClockUntil(page, () => backend.connections.length >= 6);
    const gaps = retryGaps((await socketRecords(page)).slice(0, 6));
    expect(gaps[0]).toBeGreaterThanOrEqual(100);
    expect(gaps[4]).toBeGreaterThanOrEqual(3 * gaps[1]);

    backend.acceptEveryConnection();

    await advanceClockUntil(page, () => backend.openConnections().length === 1);
    await waitForMoreFrames(backend, 3);
    await expect(alert).toBeHidden();
  });

  test('keeps saying the backend is not reachable through each reconnect attempt', async ({ page }) => {
    await page.clock.install();
    const backend = await MockBackend.attach(page);
    backend.refuseEveryConnection(DROPPED);
    const monitor = monitorPage(page);

    await page.goto('/');
    await monitor.start.click();
    await expect(monitor.linkStatus).toHaveText(/not reachable/i);
    await watchText(monitor.linkStatus, 'link');
    const connectionsBefore = backend.connections.length;

    await advanceClockUntil(page, () => backend.connections.length >= connectionsBefore + 3);
    await settleRendering(page);

    const shown = (await watchedText(page, 'link')).map((change) => change.text);
    expect(shown.filter((text) => !/not reachable/i.test(text))).toEqual([]);
  });

  test('explains MODEL_LOAD_FAILED and stops instead of retrying', async ({ page }) => {
    await page.clock.install();
    const backend = await MockBackend.attach(page);
    backend.refuseEveryConnection({ code: 1011, reason: 'MODEL_LOAD_FAILED' });
    const monitor = monitorPage(page);

    await page.goto('/');
    await monitor.start.click();

    const alert = monitor.alertWith('MODEL_LOAD_FAILED');
    await expect(alert).toBeVisible();
    await expect(alert).toContainText(/model/i);
    await expect(alert).toContainText(/restart/i);
    await expect(monitor.start).toBeVisible();

    await page.clock.runFor(PAST_ANY_BACKOFF_MS);
    await settleRendering(page);

    expect(await socketRecords(page)).toHaveLength(1);
    expect(backend.connections).toHaveLength(1);
    await expect(alert).toBeVisible();
  });

  test('explains MESSAGE_TOO_BIG when the backend closes with 1009 and does not retry', async ({ page }) => {
    await page.clock.install();
    const backend = await MockBackend.attach(page);
    backend.refuseEveryConnection({ code: 1009 });
    const monitor = monitorPage(page);

    await page.goto('/');
    await monitor.start.click();

    const alert = monitor.alertWith('MESSAGE_TOO_BIG');
    await expect(alert).toBeVisible();
    await expect(alert).toContainText(/too big|too large/i);
    await expect(alert).toContainText(/\bStart\b/);
    await expectMessageAndAction(alert, 'MESSAGE_TOO_BIG');
    await expect(monitor.start).toBeVisible();

    await page.clock.runFor(PAST_ANY_BACKOFF_MS);
    await settleRendering(page);

    expect(await socketRecords(page)).toHaveLength(1);
    expect(backend.connections).toHaveLength(1);
  });

  test('shows BACKEND_FAILED when the backend closes with 1011 for another reason', async ({ page }) => {
    await page.clock.install();
    const backend = await MockBackend.attach(page);
    backend.refuseEveryConnection({ code: 1011, reason: 'INTERNAL_ERROR' });
    const monitor = monitorPage(page);

    await page.goto('/');
    await monitor.start.click();

    const alert = monitor.alertWith('BACKEND_FAILED');
    await expect(alert).toBeVisible();
    await expect(alert).toContainText(/backend/i);
    await expect(alert).toContainText(/restart/i);
    await expectMessageAndAction(alert, 'BACKEND_FAILED');
    await expect(monitor.alertWith('MODEL_LOAD_FAILED')).toHaveCount(0);
    await expect(monitor.start).toBeVisible();

    await page.clock.runFor(PAST_ANY_BACKOFF_MS);
    await settleRendering(page);

    expect(await socketRecords(page)).toHaveLength(1);
  });

  test('shows BAD_REPLY for an unreadable reply until the next good message', async ({ page }) => {
    await page.clock.install();
    const backend = await MockBackend.attach(page);
    const monitor = monitorPage(page);
    await startMonitoring(page, backend);

    backend.sendUnreadableNext('{"type": "frame", "t": ', { holdAfter: true });

    const alert = monitor.alertWith('BAD_REPLY');
    await expect(alert).toBeVisible();
    await expectMessageAndAction(alert, 'BAD_REPLY');

    await page.clock.runFor(8000);
    await settleRendering(page);

    await expect(alert).toBeVisible();

    backend.releaseReplies();

    await expect(alert).toBeHidden();
    await waitForMoreFrames(backend, 3);
  });

  for (const wire of Object.values(WIRE_ERRORS)) {
    test(`shows its own words for ${wire.code} and keeps streaming`, async ({ page }) => {
      const backend = await MockBackend.attach(page);
      const monitor = monitorPage(page);
      await startMonitoring(page, backend);

      backend.replyNextWithError(wire, { holdAfter: true });

      const alert = monitor.alertWith(wire.code);
      await expect(alert).toBeVisible();
      await expect(alert).not.toHaveText(wire.code);
      await expect(page.getByText(wire.message)).toHaveCount(0);
      await expect(page.getByText(wire.action)).toHaveCount(0);
      const [sent] = backend.sentErrors;
      await expect.poll(() => backend.frames.length).toBeGreaterThan(sent.framesBefore);
      expect(backend.openConnections()).toHaveLength(1);

      backend.releaseReplies();
      await waitForMoreFrames(backend, 3);
    });
  }

  for (const code of ['toString', 'constructor']) {
    test(`shows the server's own message and action for the wire code ${code}`, async ({ page }) => {
      const backend = await MockBackend.attach(page);
      const monitor = monitorPage(page);
      await startMonitoring(page, backend);
      const wire = {
        code,
        message: `The backend reports a ${code} fault on this turn.`,
        action: `Wait for the next frame; report the ${code} fault if it repeats.`,
      };

      backend.replyNextWithError(wire);

      const alert = monitor.alertWith(code);
      await expect(alert).toBeVisible();
      await expect(alert).toContainText(wire.message);
      await expect(alert).toContainText(wire.action);
      await waitForMoreFrames(backend, 3);
    });
  }

  test('tells where to open the page in the SOCKET_UNAVAILABLE action', async ({ page }) => {
    await page.clock.install();
    const backend = await MockBackend.attach(page);
    backend.refuseEveryConnection(DROPPED);
    const monitor = monitorPage(page);

    await page.goto('/');
    await monitor.start.click();

    const alert = monitor.alertWith('SOCKET_UNAVAILABLE');
    await expect(alert).toBeVisible();
    await expect(alert).toContainText('http://127.0.0.1:4173');
    await expect(alert).toContainText(/already running/i);
  });

  test('says the stream may have stalled and to press Stop, then Start, in BAD_REPLY', async ({ page }) => {
    await page.clock.install();
    const backend = await MockBackend.attach(page);
    const monitor = monitorPage(page);
    await startMonitoring(page, backend);

    backend.sendUnreadableNext('{"type": "frame", "t": ', { holdAfter: true });

    const alert = monitor.alertWith('BAD_REPLY');
    await expect(alert).toBeVisible();
    await expect(alert).toContainText(/stall/i);
    await expect(alert).toContainText(/\bStop\b,? then\b[^.]*\bStart\b/);
    await expect(alert).toContainText(/latest code/i);
    await expect(alert).toContainText(/rebuild/i);
    await expect(alert).toContainText(/restart\w* the backend/i);

    backend.releaseReplies();
    await expect(alert).toBeHidden();
  });

  test('points MODEL_LOAD_FAILED at the backend terminal and the backend folder', async ({ page }) => {
    await page.clock.install();
    const backend = await MockBackend.attach(page);
    backend.refuseEveryConnection({ code: 1011, reason: 'MODEL_LOAD_FAILED' });
    const monitor = monitorPage(page);

    await page.goto('/');
    await monitor.start.click();

    const alert = monitor.alertWith('MODEL_LOAD_FAILED');
    await expect(alert).toBeVisible();
    await expect(alert).toContainText(/terminal/i);
    await expect(alert).toContainText('backend/');
    await expect(alert).toContainText(/restart/i);
    await expect(alert).toContainText(/\bStart\b/);
  });

  test('says to close the other tab or press Stop there while another connection holds the backend', async ({
    page,
  }) => {
    await page.clock.install();
    const backend = await MockBackend.attach(page);
    backend.refuseEveryConnection(ANOTHER_CONNECTION_OPEN);
    const monitor = monitorPage(page);

    await page.goto('/');
    await monitor.start.click();
    await advanceClockUntil(page, () => backend.connections.length >= 2);

    await expect(monitor.linkStatus).toContainText(/\bclos(e|ing)\b[^.]*\bother tab\b/i);
    await expect(monitor.linkStatus).toContainText(/\bStop\b/);
  });

  test('keeps naming the other tab through each reconnect attempt while another connection holds the backend', async ({
    page,
  }) => {
    await page.clock.install();
    const backend = await MockBackend.attach(page);
    backend.refuseEveryConnection(ANOTHER_CONNECTION_OPEN);
    const monitor = monitorPage(page);

    await page.goto('/');
    await monitor.start.click();
    await expect(monitor.linkStatus).toContainText(/\bother tab\b/i);
    await watchText(monitor.linkStatus, 'busy-link');
    const connectionsBefore = backend.connections.length;

    await advanceClockUntil(page, () => backend.connections.length >= connectionsBefore + 3);
    await settleRendering(page);

    const shown = (await watchedText(page, 'busy-link')).map((change) => change.text);
    expect(shown.filter((text) => !/\bother tab\b/i.test(text))).toEqual([]);
  });

  for (const empty of ['message', 'action'] as const) {
    test(`shows the page's own fallback text when a wire error has an empty ${empty}`, async ({ page }) => {
      const backend = await MockBackend.attach(page);
      const monitor = monitorPage(page);
      await startMonitoring(page, backend);
      const wire = {
        code: 'TURN_FAILED',
        message: 'The backend could not finish this turn.',
        action: 'Wait for the next frame; report it if it repeats.',
        [empty]: '',
      };
      const kept = empty === 'message' ? wire.action : wire.message;

      backend.replyNextWithError(wire);

      const alert = monitor.alertWith('TURN_FAILED');
      await expect(alert).toBeVisible();
      await expect(alert).toContainText(kept);
      expect(ownTextLength(await alert.innerText(), 'TURN_FAILED', kept)).toBeGreaterThan(20);
      await waitForMoreFrames(backend, 3);
    });
  }

  test('ignores duplicate turn replies so two frames are never in flight', async ({ page }) => {
    const backend = await MockBackend.attach(page);
    await startMonitoring(page, backend);
    await waitForMoreFrames(backend, 3);
    const [streaming] = backend.openConnections();

    const expectOneFrameInFlight = () => {
      const frames = backend.framesOn(streaming.id);
      expect(frames.flatMap((frame, index) => (frame.arrivedWhileAwaitingReply ? [index] : []))).toEqual([]);
      expect(Math.min(...gapsBetween(frames.map((frame) => frame.captureMs)))).toBeGreaterThanOrEqual(34);
    };

    await test.step('a duplicate reply during the spacing wait', async () => {
      for (let round = 0; round < 6; round += 1) {
        const sent = backend.sentDuplicates.length;
        backend.duplicateNextReply('during-spacing-wait');
        await expect.poll(() => backend.sentDuplicates.length).toBe(sent + 1);
        await waitForMoreFrames(backend, 3);
      }
      expectOneFrameInFlight();
    });

    await test.step('a duplicate reply after the next frame is sent', async () => {
      backend.setReplyDelay(150);
      for (let round = 0; round < 3; round += 1) {
        const sent = backend.sentDuplicates.length;
        backend.duplicateNextReply('after-next-frame');
        await expect.poll(() => backend.sentDuplicates.length).toBe(sent + 1);
        await waitForMoreFrames(backend, 3);
      }
      expectOneFrameInFlight();
    });
  });
});
