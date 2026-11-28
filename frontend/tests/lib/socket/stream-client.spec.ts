import { expect, test, type Page } from '@playwright/test';
import { expectQuietRef, guidedPage, openGuidedRun, RUN_MS, startCheck, startRun } from '../../support/guided-page';
import { frameSends, gapsBetween } from '../../support/frame-timing';
import { MockBackend, STREAM_URL, WIRE_ERRORS } from '../../support/mock-backend';
import { settleRendering, waitForMoreFrames } from '../../support/page-helpers';
import { socketRecords } from '../../support/socket-recorder';

const WAIT_AFTER_CLOSE_MS = 20000;

const TERMINAL_CLOSES = [
  {
    code: 'MODEL_LOAD_FAILED',
    close: { code: 1011, reason: 'MODEL_LOAD_FAILED' },
    message: "The pulse reader couldn't load the part that finds your face, so the run stopped.",
  },
  {
    code: 'MESSAGE_TOO_BIG',
    close: { code: 1009 },
    message: "The pulse reader hung up because this page sent far too much at once. That's a bug in this page.",
  },
  {
    code: 'BACKEND_FAILED',
    close: { code: 1011, reason: 'INTERNAL_ERROR' },
    message: 'The pulse reader tripped over its own feet, so the run stopped.',
  },
];

type WireCode = keyof typeof WIRE_ERRORS;

const PLAIN_WIRE_WORDS: Record<WireCode, string> = {
  BAD_FRAME: "A split second of video couldn't be read, so it was skipped.",
  BAD_TIMESTAMP: "A split second of video arrived with a time that didn't add up, so it was skipped.",
  FRAME_TOO_LARGE: 'A split second of video was too big to read, so it was skipped.',
  RATE_LIMITED: 'Video came in faster than the pulse reader takes it, so a split second was dropped.',
};

const UNKNOWN_CODE_MESSAGE = "The pulse reader flagged a problem but didn't say what.";

const BAD_REPLY_MESSAGE =
  "The pulse reader sent something this page can't read, so it was ignored. The numbers may stall.";

const UNREACHABLE_MESSAGE = "Can't reach the pulse reader, so the run stopped.";
const BUSY_MESSAGE = 'The app is busy in another tab or window, so the run stopped.';
const CAMERA_OFF_STOPPED = "Camera's off. The run stopped.";

const LINK_LOSSES = [
  {
    name: 'drops without a close frame',
    close: { code: 1006 },
    code: 'SOCKET_UNAVAILABLE',
    message: UNREACHABLE_MESSAGE,
  },
  { name: 'closes normally', close: { code: 1000 }, code: 'SOCKET_UNAVAILABLE', message: UNREACHABLE_MESSAGE },
  { name: 'goes away', close: { code: 1001 }, code: 'SOCKET_UNAVAILABLE', message: UNREACHABLE_MESSAGE },
  {
    name: 'says another connection is open',
    close: { code: 1013, reason: 'ANOTHER_CONNECTION_OPEN' },
    code: 'SOCKET_BUSY',
    message: BUSY_MESSAGE,
  },
];

const START_REFUSALS = [
  { name: 'is not there', close: { code: 1006 }, code: 'SOCKET_UNAVAILABLE', message: UNREACHABLE_MESSAGE },
  {
    name: 'is busy with another connection',
    close: { code: 1013, reason: 'ANOTHER_CONNECTION_OPEN' },
    code: 'SOCKET_BUSY',
    message: BUSY_MESSAGE,
  },
];

type RefusedSocketsWindow = Window & { refusedSockets: { count: number } };

async function refuseSocketConstruction(page: Page): Promise<void> {
  await page.addInitScript((url) => {
    const refused = { count: 0 };
    Object.defineProperty(globalThis, 'refusedSockets', { value: refused });
    const Real = globalThis.WebSocket;
    globalThis.WebSocket = class RefusingSocket extends Real {
      constructor(target: string | URL, protocols?: string | string[]) {
        if (String(target) === url) {
          refused.count += 1;
          throw new DOMException('The test refused to open this socket.', 'SecurityError');
        }
        super(target, protocols);
      }
    };
  }, STREAM_URL);
}

function refusedSocketCount(page: Page): Promise<number> {
  return page.evaluate(() => (globalThis as unknown as RefusedSocketsWindow).refusedSockets.count);
}

async function expectNoSecondConnection(page: Page, backend: MockBackend): Promise<void> {
  backend.acceptEveryConnection();
  await page.clock.runFor(RUN_MS);
  await settleRendering(page);
  expect(await socketRecords(page)).toHaveLength(1);
  expect(backend.connections).toHaveLength(1);
  expect(backend.openConnections()).toEqual([]);
}

async function sendTimesAsReceived(page: Page, backend: MockBackend): Promise<number[]> {
  let sent: number[] = [];
  await expect
    .poll(async () => {
      sent = (await frameSends(page)).map((send) => send.at);
      return sent.length === backend.frames.length;
    })
    .toBe(true);
  return sent;
}

async function expectOneConnectionOnly(page: Page, backend: MockBackend): Promise<void> {
  await page.clock.runFor(WAIT_AFTER_CLOSE_MS);
  await settleRendering(page);
  expect(await socketRecords(page)).toHaveLength(1);
  expect(backend.connections).toHaveLength(1);
}

test.describe('stream socket client', () => {
  test('keeps exactly one connection open during a guided run', async ({ page }) => {
    const backend = await MockBackend.attach(page);

    await startRun(page, backend);
    await waitForMoreFrames(backend, 5);

    const open = backend.openConnections();
    expect(open).toHaveLength(1);
    expect(backend.framesOn(open[0].id).length).toBeGreaterThanOrEqual(5);
  });

  test('waits for the turn reply before sending the next frame', async ({ page }) => {
    const backend = await MockBackend.attach(page, 'browser');
    backend.setReplyDelay(250);

    await startCheck(page, backend);
    await waitForMoreFrames(backend, 4);

    expect(backend.frames.filter((frame) => frame.arrivedWhileAwaitingReply)).toEqual([]);
  });

  test('spaces frame sends at least 34 ms apart', async ({ page }) => {
    const backend = await MockBackend.attach(page, 'browser');

    await startCheck(page, backend);
    await waitForMoreFrames(backend, 25);

    const sent = await sendTimesAsReceived(page, backend);
    const [streaming] = backend.openConnections();
    const frames = backend.framesOn(streaming.id);
    expect(sent.length, 'frame sends seen by the page').toBeGreaterThanOrEqual(2);
    expect(sent.length, 'frame sends against frames at the backend').toBe(frames.length);
    const arrivalGaps = gapsBetween(frames.map((frame) => frame.arrivedAt));
    expect(Math.min(...gapsBetween(sent))).toBeGreaterThanOrEqual(34);
    expect(Math.min(...arrivalGaps)).toBeGreaterThanOrEqual(25);
  });

  for (const terminal of TERMINAL_CLOSES) {
    test(`stops with a quiet Ref: ${terminal.code} and never reconnects when the backend closes that way`, async ({
      page,
    }) => {
      await page.clock.install();
      const backend = await MockBackend.attach(page);
      backend.refuseEveryConnection(terminal.close);
      const guided = guidedPage(page);

      await openGuidedRun(page);
      await guided.start.click();

      await expectQuietRef(guided.main, terminal.message, terminal.code);
      await expect(guided.stop).toHaveCount(0);

      await expectOneConnectionOnly(page, backend);
      await expect(guided.main.getByText(terminal.message)).toBeVisible();
    });
  }

  for (const loss of LINK_LOSSES) {
    test(`stops the run with a quiet Ref: ${loss.code} and never opens a second connection when the link ${loss.name} mid-run`, async ({
      page,
    }) => {
      await page.clock.install();
      const backend = await MockBackend.attach(page);
      const guided = guidedPage(page);
      await startRun(page, backend);

      backend.dropOpenConnections(loss.close);

      await expectQuietRef(guided.main, loss.message, loss.code);
      await expect(guided.main.getByText(CAMERA_OFF_STOPPED, { exact: true })).toBeVisible();
      await expect(guided.startAgain).toBeVisible();
      await expect(guided.stop).toHaveCount(0);

      await expectNoSecondConnection(page, backend);
      await expectQuietRef(guided.main, loss.message, loss.code);
      await expect(guided.startAgain).toBeVisible();
    });
  }

  for (const refusal of START_REFUSALS) {
    test(`stops at Start with a quiet Ref: ${refusal.code} and never knocks again when the pulse reader ${refusal.name}`, async ({
      page,
    }) => {
      await page.clock.install();
      const backend = await MockBackend.attach(page);
      backend.refuseEveryConnection(refusal.close);
      const guided = guidedPage(page);
      await openGuidedRun(page);

      await guided.start.click();

      await expectQuietRef(guided.main, refusal.message, refusal.code);
      await expect(guided.startAgain).toBeVisible();
      await expect(guided.stop).toHaveCount(0);

      await expectNoSecondConnection(page, backend);
      await expectQuietRef(guided.main, refusal.message, refusal.code);
      expect(backend.frames).toEqual([]);
    });
  }

  test('stops with a quiet Ref: SOCKET_UNAVAILABLE and tries no second socket when the browser will not open one', async ({
    page,
  }) => {
    await page.clock.install();
    const backend = await MockBackend.attach(page);
    await refuseSocketConstruction(page);
    const guided = guidedPage(page);
    await openGuidedRun(page);

    await guided.start.click();

    await expectQuietRef(guided.main, UNREACHABLE_MESSAGE, 'SOCKET_UNAVAILABLE');
    await expect(guided.main.getByText(CAMERA_OFF_STOPPED, { exact: true })).toBeVisible();
    await expect(guided.startAgain).toBeVisible();

    await page.clock.runFor(RUN_MS);
    await settleRendering(page);
    expect(await refusedSocketCount(page)).toBe(1);
    expect(backend.connections).toEqual([]);
    await expectQuietRef(guided.main, UNREACHABLE_MESSAGE, 'SOCKET_UNAVAILABLE');
  });

  test('opens exactly one new connection for Start again after a dropped link, and keeps it', async ({ page }) => {
    await page.clock.install();
    const backend = await MockBackend.attach(page);
    const guided = guidedPage(page);
    await startRun(page, backend);
    backend.dropOpenConnections({ code: 1006 });
    await expect(guided.startAgain).toBeVisible();
    await page.clock.runFor(30000);

    await guided.startAgain.click();

    await expect.poll(() => backend.openConnections().length).toBe(1);
    await expect(guided.stop).toBeVisible();
    await expect(guided.main.getByText('Ref: SOCKET_UNAVAILABLE', { exact: true })).toHaveCount(0);
    expect(backend.connections).toHaveLength(2);
    expect(await socketRecords(page)).toHaveLength(2);
  });

  test('shows a quiet Ref: BAD_REPLY for an unreadable reply and keeps streaming on the same connection', async ({
    page,
  }) => {
    const backend = await MockBackend.attach(page);
    const guided = guidedPage(page);
    await startRun(page, backend);
    const [streaming] = backend.openConnections();

    backend.sendUnreadableNext('{"type": "frame", "t": ', { holdAfter: true });

    await expectQuietRef(guided.main, BAD_REPLY_MESSAGE, 'BAD_REPLY');
    await expect(guided.stop).toBeVisible();

    backend.releaseReplies();

    await waitForMoreFrames(backend, 3);
    expect(backend.openConnections().map((connection) => connection.id)).toEqual([streaming.id]);
    await expect(guided.stop).toBeVisible();
  });

  for (const [code, wire] of Object.entries(WIRE_ERRORS) as Array<[WireCode, (typeof WIRE_ERRORS)[WireCode]]>) {
    test(`keeps streaming on one connection after a ${code} reply, in plain words, never the server's`, async ({
      page,
    }) => {
      const backend = await MockBackend.attach(page);
      const guided = guidedPage(page);
      await startRun(page, backend);

      backend.replyNextWithError(wire, { holdAfter: true });

      await expectQuietRef(guided.main, PLAIN_WIRE_WORDS[code], code);
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
    test(`treats the wire code ${code} as unknown, never as a known word list entry`, async ({ page }) => {
      const backend = await MockBackend.attach(page);
      const guided = guidedPage(page);
      await startRun(page, backend);
      const wire = {
        code,
        message: `The backend reports a ${code} fault on this turn.`,
        action: `Wait for the next frame; report the ${code} fault if it repeats.`,
      };

      backend.replyNextWithError(wire);

      await expect(guided.main.getByText(UNKNOWN_CODE_MESSAGE)).toBeVisible();
      await expect(guided.main.getByText(`Ref: ${code}`, { exact: true })).toBeVisible();
      await expect(page.getByText(wire.message)).toHaveCount(0);
      await expect(page.getByText(wire.action)).toHaveCount(0);
      await waitForMoreFrames(backend, 3);
      await expect(guided.stop).toBeVisible();
    });
  }

  test('ignores duplicate turn replies so two frames are never in flight', async ({ page }) => {
    const backend = await MockBackend.attach(page);
    await startRun(page, backend);
    await waitForMoreFrames(backend, 3);
    const [streaming] = backend.openConnections();

    const expectOneFrameInFlight = async () => {
      const sent = await sendTimesAsReceived(page, backend);
      const frames = backend.framesOn(streaming.id);
      expect(frames.flatMap((frame, index) => (frame.arrivedWhileAwaitingReply ? [index] : []))).toEqual([]);
      expect(sent.length, 'frame sends seen by the page').toBeGreaterThanOrEqual(2);
      expect(sent.length, 'frame sends against frames at the backend').toBe(frames.length);
      expect(Math.min(...gapsBetween(sent))).toBeGreaterThanOrEqual(34);
    };

    await test.step('a duplicate reply during the spacing wait', async () => {
      for (let round = 0; round < 6; round += 1) {
        const sent = backend.sentDuplicates.length;
        backend.duplicateNextReply('during-spacing-wait');
        await expect.poll(() => backend.sentDuplicates.length).toBe(sent + 1);
        await waitForMoreFrames(backend, 3);
      }
      await expectOneFrameInFlight();
    });

    await test.step('a duplicate reply after the next frame is sent', async () => {
      backend.setReplyDelay(150);
      for (let round = 0; round < 3; round += 1) {
        const sent = backend.sentDuplicates.length;
        backend.duplicateNextReply('after-next-frame');
        await expect.poll(() => backend.sentDuplicates.length).toBe(sent + 1);
        await waitForMoreFrames(backend, 3);
      }
      await expectOneFrameInFlight();
    });
  });
});
