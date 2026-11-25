import { expect, test } from '@playwright/test';
import {
  advanceRun,
  expectCurrentStep,
  expectQuietRef,
  guidedPage,
  startRun,
  timerSeconds,
} from '../../support/guided-page';
import { MockBackend, WIRE_ERRORS } from '../../support/mock-backend';
import { waitForMoreFrames } from '../../support/page-helpers';

const NOTICE_SHOWN_MS = 5000;
const CARRIES_ON = 'Nothing to do; the run carries on.';
const UNKNOWN_WIRE_ERROR = {
  code: 'READER_HICCUP',
  message: 'Traceback in pulse_frame.stream.processor at line 42',
  action: 'Restart uvicorn with the reload flag',
};

const BAD_FRAME_WORDS = "A split second of video couldn't be read, so it was skipped.";
const UNKNOWN_WORDS = "The pulse reader flagged a problem but didn't say what.";
const BAD_REPLY_WORDS =
  "The pulse reader sent something this page can't read, so it was ignored. The numbers may stall.";
const SERVER_MESSAGE = 'Traceback in pulse_frame.stream.processor at line 42';
const SERVER_ACTION = 'Restart uvicorn with the reload flag';
const OLD_FALLBACK = /did not say what|already on its way|flagged a problem with this turn/;

const BLANK_WIRE_ERRORS = [
  {
    name: 'a known code with an empty message and action',
    error: { code: 'BAD_FRAME', message: '', action: '' },
    words: BAD_FRAME_WORDS,
  },
  {
    name: 'a known code with a blank message',
    error: { code: 'BAD_FRAME', message: '   ', action: SERVER_ACTION },
    words: BAD_FRAME_WORDS,
  },
  {
    name: 'an unknown code with an empty message and action',
    error: { code: 'READER_HICCUP', message: '', action: '' },
    words: UNKNOWN_WORDS,
  },
  {
    name: 'an unknown code with an empty message',
    error: { code: 'READER_HICCUP', message: '', action: SERVER_ACTION },
    words: UNKNOWN_WORDS,
  },
  {
    name: 'an unknown code with a blank action',
    error: { code: 'READER_HICCUP', message: SERVER_MESSAGE, action: ' \n ' },
    words: UNKNOWN_WORDS,
  },
];

const PARTIAL_WIRE_ERRORS = [
  { name: 'no message', fields: { type: 'error', code: 'READER_HICCUP', action: SERVER_ACTION } },
  { name: 'no action', fields: { type: 'error', code: 'BAD_FRAME', message: SERVER_MESSAGE } },
];

test.describe('guided run wire messages', () => {
  for (const blank of BLANK_WIRE_ERRORS) {
    test(`shows ${blank.name} in plain words with a quiet Ref, never the server's words or an old fallback`, async ({
      page,
    }) => {
      await page.clock.install();
      const backend = await MockBackend.attach(page);
      const guided = guidedPage(page);
      await startRun(page, backend);

      backend.replyNextWithError(blank.error);

      await expectQuietRef(guided.main, blank.words, blank.error.code);
      await expect(guided.main.getByText(CARRIES_ON)).toBeVisible();
      await expect(guided.main).not.toContainText(OLD_FALLBACK);
      await expect(guided.main).not.toContainText(/Traceback|pulse_frame|uvicorn|reload flag/);
      await expectCurrentStep(page, 'Warm-up');
      await waitForMoreFrames(backend, 3);
      await expect(guided.stop).toBeVisible();
    });
  }

  for (const partial of PARTIAL_WIRE_ERRORS) {
    test(`treats a wire error with ${partial.name} as an unreadable reply with a quiet Ref: BAD_REPLY, never the server's words`, async ({
      page,
    }) => {
      await page.clock.install();
      const backend = await MockBackend.attach(page);
      const guided = guidedPage(page);
      await startRun(page, backend);

      backend.sendUnreadableNext(JSON.stringify(partial.fields), { holdAfter: true });

      await expectQuietRef(guided.main, BAD_REPLY_WORDS, 'BAD_REPLY');
      await expect(guided.main.getByText(`Ref: ${partial.fields.code}`, { exact: true })).toHaveCount(0);
      await expect(guided.main).not.toContainText(OLD_FALLBACK);
      await expect(guided.main).not.toContainText(/Traceback|pulse_frame|uvicorn|reload flag/);
      await expect(guided.stop).toBeVisible();

      backend.releaseReplies();
      await waitForMoreFrames(backend, 3);
      await expect(guided.stop).toBeVisible();
    });
  }

  test('shows a wire error mid-run in plain words with a quiet Ref last and the run carrying on', async ({ page }) => {
    await page.clock.install();
    const backend = await MockBackend.attach(page);
    const guided = guidedPage(page);
    await startRun(page, backend);

    backend.replyNextWithError(WIRE_ERRORS.BAD_FRAME);

    await expectQuietRef(guided.main, "A split second of video couldn't be read, so it was skipped.", 'BAD_FRAME');
    await expect(guided.main.getByText(CARRIES_ON)).toBeVisible();
    await expect(guided.main).not.toContainText(WIRE_ERRORS.BAD_FRAME.message);
    await expect(guided.main).not.toContainText(/backend/i);
    await expectCurrentStep(page, 'Warm-up');
    await expect(guided.stop).toBeVisible();
  });

  test("shows an unknown wire code with the plain fallback and the code as Ref, never the reader's words", async ({
    page,
  }) => {
    await page.clock.install();
    const backend = await MockBackend.attach(page);
    const guided = guidedPage(page);
    await startRun(page, backend);

    backend.replyNextWithError(UNKNOWN_WIRE_ERROR);

    await expectQuietRef(guided.main, "The pulse reader flagged a problem but didn't say what.", 'READER_HICCUP');
    await expect(guided.main.getByText(CARRIES_ON)).toBeVisible();
    await expect(guided.main).not.toContainText(/Traceback|pulse_frame|uvicorn|reload flag/);
    await expectCurrentStep(page, 'Warm-up');
  });

  test('clears a wire notice after the notice time while the run carries on', async ({ page }) => {
    await page.clock.install();
    const backend = await MockBackend.attach(page);
    const guided = guidedPage(page);
    await startRun(page, backend);
    const notice = guided.main.getByText(
      'Video came in faster than the pulse reader takes it, so a split second was dropped.',
    );

    backend.replyNextWithError(WIRE_ERRORS.RATE_LIMITED);
    await expect(notice).toBeVisible();
    await expect(guided.main.getByText('Ref: RATE_LIMITED', { exact: true })).toBeVisible();
    const before = await timerSeconds(guided.warmUpTimer);

    await advanceRun(page, backend, NOTICE_SHOWN_MS + 1000, 1000);

    await expect(notice).toHaveCount(0);
    await expect(guided.main.getByText('Ref: RATE_LIMITED', { exact: true })).toHaveCount(0);
    await expectCurrentStep(page, 'Warm-up');
    expect(await timerSeconds(guided.warmUpTimer)).toBeLessThanOrEqual(before - 5);
    await waitForMoreFrames(backend, 3);
    await expect(guided.stop).toBeVisible();
  });
});
