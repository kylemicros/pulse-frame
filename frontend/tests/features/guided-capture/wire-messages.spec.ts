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
import { waitForMoreFrames } from '../../support/monitor-page';

const NOTICE_SHOWN_MS = 5000;
const CARRIES_ON = 'Nothing to do; the run carries on.';
const UNKNOWN_WIRE_ERROR = {
  code: 'READER_HICCUP',
  message: 'Traceback in pulse_frame.stream.processor at line 42',
  action: 'Restart uvicorn with the reload flag',
};

test.describe('guided run wire messages', () => {
  test('shows a wire error mid-run in plain words with a quiet Ref last and the run carrying on', async ({ page }) => {
    await page.clock.install();
    const backend = await MockBackend.attach(page);
    const guided = guidedPage(page);
    await startRun(page, backend);

    backend.replyNextWithError(WIRE_ERRORS.BAD_FRAME);

    await expectQuietRef(guided.panel, "A split second of video couldn't be read, so it was skipped.", 'BAD_FRAME');
    await expect(guided.panel.getByText(CARRIES_ON)).toBeVisible();
    await expect(guided.panel).not.toContainText(WIRE_ERRORS.BAD_FRAME.message);
    await expect(guided.panel).not.toContainText(/backend/i);
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

    await expectQuietRef(guided.panel, "The pulse reader flagged a problem but didn't say what.", 'READER_HICCUP');
    await expect(guided.panel.getByText(CARRIES_ON)).toBeVisible();
    await expect(guided.panel).not.toContainText(/Traceback|pulse_frame|uvicorn|reload flag/);
    await expectCurrentStep(page, 'Warm-up');
  });

  test('clears a wire notice after the notice time while the run carries on', async ({ page }) => {
    await page.clock.install();
    const backend = await MockBackend.attach(page);
    const guided = guidedPage(page);
    await startRun(page, backend);
    const notice = guided.panel.getByText(
      'Video came in faster than the pulse reader takes it, so a split second was dropped.',
    );

    backend.replyNextWithError(WIRE_ERRORS.RATE_LIMITED);
    await expect(notice).toBeVisible();
    await expect(guided.panel.getByText('Ref: RATE_LIMITED', { exact: true })).toBeVisible();
    const before = await timerSeconds(guided.warmUpTimer);

    await advanceRun(page, backend, NOTICE_SHOWN_MS + 1000, 1000);

    await expect(notice).toHaveCount(0);
    await expect(guided.panel.getByText('Ref: RATE_LIMITED', { exact: true })).toHaveCount(0);
    await expectCurrentStep(page, 'Warm-up');
    expect(await timerSeconds(guided.warmUpTimer)).toBeLessThanOrEqual(before - 5);
    await waitForMoreFrames(backend, 3);
    await expect(guided.stop).toBeVisible();
  });
});
