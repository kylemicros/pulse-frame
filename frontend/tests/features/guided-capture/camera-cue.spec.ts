import { expect, test, type Locator } from '@playwright/test';
import { reachFarCheck, rectOf, startRunAt } from '../../support/app-shell';
import { advanceRunUntil, BOLD, guidedPage, pushAndConfirm, SETUP_PROMPTS } from '../../support/guided-page';
import { drawnTexts } from '../../support/result-states';
import { underAriaHidden } from '../../support/settings';

const FAR = SETUP_PROMPTS.far;
const WARM_UP_CUE = 'Keep your face in the oval. Look wherever you like.';
const COUNTING_CUE = 'Hold still. Shoulders loose, hands in your lap.';
const EDGE_SLACK_PX = 0.5;

const CHIP_VIEWPORTS = [
  { name: 'desktop', size: { width: 1280, height: 800 } },
  { name: 'tablet', size: { width: 820, height: 1180 } },
] as const;

async function timesDrawn(scope: Locator, text: string): Promise<number> {
  return (await drawnTexts(scope)).filter((each) => each === text).length;
}

async function expectUnderCameraAbove(cue: Locator, camera: Locator, headline: Locator): Promise<void> {
  const cueRect = await rectOf(cue);
  const cameraRect = await rectOf(camera);
  const headlineRect = await rectOf(headline);
  expect(cueRect.top, 'the cue top against the camera bottom').toBeGreaterThanOrEqual(cameraRect.bottom - EDGE_SLACK_PX);
  expect(cueRect.bottom, 'the cue bottom against the step headline top').toBeLessThanOrEqual(headlineRect.top + EDGE_SLACK_PX);
}

for (const viewport of CHIP_VIEWPORTS) {
  test.describe(`the setup prompt on the camera at ${viewport.name} size`, () => {
    test.use({ viewport: viewport.size });

    test('draws the prompt once, as a chip on the camera, with only its line drawn in the panel', async ({ page }) => {
      await reachFarCheck(page);
      const guided = guidedPage(page);

      expect(await timesDrawn(guided.main, FAR.prompt), 'times the prompt is drawn on the page').toBe(1);
      expect(await timesDrawn(guided.cameraBox, FAR.prompt), 'the prompt drawn on the camera').toBe(1);
      expect(await underAriaHidden(guided.cameraCue(FAR.prompt)), 'the camera chip is hidden from screen readers').toBe(true);
      expect(await timesDrawn(guided.setupPrompt, FAR.prompt), 'the prompt drawn in the panel').toBe(0);
      expect(await drawnTexts(guided.setupPrompt), 'the panel draws the line').toContain(FAR.line);
      await expect(guided.setupPrompt).toHaveText(`${FAR.prompt} ${FAR.line}`);
      expect(await underAriaHidden(guided.setupPrompt), 'the panel box is read by screen readers').toBe(false);
    });

    test('keeps the prompt chip clear of the lock', async ({ page }) => {
      await reachFarCheck(page);
      const guided = guidedPage(page);

      const chip = await rectOf(guided.cameraCue(FAR.prompt));
      const lock = await rectOf(guided.lock);
      const apart = chip.top >= lock.bottom || chip.bottom <= lock.top || chip.left >= lock.right || chip.right <= lock.left;
      expect(apart, `the chip ${JSON.stringify(chip)} and the lock ${JSON.stringify(lock)} overlap`).toBe(true);
    });
  });
}

test.describe('the camera cues on a phone', () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test('puts the setup prompt under the camera, never over the face, drawn once in bold with its line', async ({ page }) => {
    await reachFarCheck(page);
    const guided = guidedPage(page);

    expect(await timesDrawn(guided.cameraBox, FAR.prompt), 'the prompt drawn over the camera').toBe(0);
    expect(await timesDrawn(guided.main, FAR.prompt), 'times the prompt is drawn on the page').toBe(1);
    expect(await timesDrawn(guided.setupPrompt, FAR.prompt), 'the prompt drawn in its box').toBe(1);
    await expect(guided.setupPrompt.getByText(FAR.prompt, { exact: true })).toHaveCSS('font-weight', BOLD);
    expect(await drawnTexts(guided.setupPrompt), 'the box draws the line').toContain(FAR.line);
    expect(await underAriaHidden(guided.setupPrompt), 'the box is read by screen readers').toBe(false);
    await expectUnderCameraAbove(guided.setupPrompt, guided.cameraBox, guided.headline('Quick setup check'));
  });

  test('puts the warm-up and the counting cues under the camera, never over the face', async ({ page }) => {
    const backend = await startRunAt(page, '/');
    const guided = guidedPage(page);
    const warmUpCue = guided.main.getByText(WARM_UP_CUE, { exact: true });
    await expect(warmUpCue).toBeVisible();

    expect(await timesDrawn(guided.cameraBox, WARM_UP_CUE), 'the warm-up cue over the camera').toBe(0);
    expect(await timesDrawn(guided.main, WARM_UP_CUE), 'times the warm-up cue is drawn').toBe(1);
    await expectUnderCameraAbove(warmUpCue, guided.cameraBox, guided.headline('Stay in frame. No need to watch.'));

    await pushAndConfirm(page, backend, { bpm: 68.2, quality_db: 9.4, state: 'ok' });
    await advanceRunUntil(page, backend, guided.countedTimer);
    const countingCue = guided.main.getByText(COUNTING_CUE, { exact: true });
    await expect(countingCue).toBeVisible();

    expect(await timesDrawn(guided.cameraBox, COUNTING_CUE), 'the counting cue over the camera').toBe(0);
    expect(await timesDrawn(guided.main, COUNTING_CUE), 'times the counting cue is drawn').toBe(1);
    await expectUnderCameraAbove(countingCue, guided.cameraBox, guided.headline('Counting. Hold still.'));
  });
});
