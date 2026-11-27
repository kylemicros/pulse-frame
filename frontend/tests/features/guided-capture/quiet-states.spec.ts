import { expect, test, type Page } from '@playwright/test';
import { barRect, reachState, rectOf, shell, type GuidedState } from '../../support/app-shell';
import {
  advanceRun,
  guidedPage,
  openGuidedRun,
  RUN_STOPPED_TEXT,
  startCheck,
  startRun,
  VARIATION_LINE,
} from '../../support/guided-page';
import { MockBackend } from '../../support/mock-backend';
import { refuseCamera } from '../../support/page-helpers';
import {
  drawnTexts,
  expectNoResultTiles,
  fontPx,
  IDLE_CAMERA_LABEL,
  IDLE_HEADLINE,
  idleHeadline,
  OLD_IDLE_CAMERA_LINE,
  RANGED_READING,
  reachCameraLostInWarmUp,
  reachResult,
  scrollPageToTop,
} from '../../support/result-states';
import { drawn, openSettings, PRIVACY_SENTENCE, settingsPanel, underAriaHidden } from '../../support/settings';

const DESKTOP = { width: 1280, height: 800 } as const;
const PHONE = { width: 390, height: 844 } as const;
const PLAN_TITLE = 'Two and a half minutes, mostly doing nothing.';
const CAMERA_DROPPED_LINE = "Camera's off. It dropped out.";

async function openIdle(page: Page): Promise<void> {
  await MockBackend.attach(page);
  await openGuidedRun(page);
  await expect(guidedPage(page).start).toBeVisible();
}

async function reachCameraDenied(page: Page): Promise<void> {
  await refuseCamera(page, 'NotAllowedError');
  await openIdle(page);
  await guidedPage(page).start.click();
  await expect(guidedPage(page).alert).toContainText('Ref: CAMERA_DENIED');
}

function faceGuideDrawn(page: Page): Promise<boolean> {
  return guidedPage(page).cameraBox.evaluate((box) =>
    Array.from(box.querySelectorAll('svg ellipse')).some((shape) => {
      const rect = shape.getBoundingClientRect();
      return rect.width > 2 && rect.height > 2;
    }),
  );
}

test.describe('the quiet idle page on a desktop', () => {
  test.use({ viewport: DESKTOP });

  test('shows the empty camera box with only the face guide and the lock, no words on it', async ({ page }) => {
    await openIdle(page);
    const guided = guidedPage(page);

    await expect(guided.lock).toBeVisible();
    expect(await faceGuideDrawn(page), 'the dashed face guide is drawn on the camera box').toBe(true);
    expect(await drawnTexts(guidedPage(page).cameraBox), 'words drawn on the idle camera box').toEqual([]);
    await expect(guided.main.getByText(OLD_IDLE_CAMERA_LINE)).toHaveCount(0);
  });

  test('tells screen readers the camera is off until Start with a label that is not drawn', async ({ page }) => {
    await openIdle(page);
    const label = guidedPage(page).cameraBox.getByText(IDLE_CAMERA_LABEL, { exact: true });

    await expect(label).toHaveCount(1);
    expect(await drawn(label), 'the label is drawn on screen').toBe(false);
    expect(await underAriaHidden(label), 'the label is hidden from screen readers').toBe(false);
  });

  test('puts the idle headline "Sit still. Your face does the rest." large under the camera', async ({ page }) => {
    await openIdle(page);
    const headline = idleHeadline(page);
    await expect(headline).toBeVisible();

    const camera = await rectOf(guidedPage(page).cameraBox);
    const text = await rectOf(headline);
    const panel = await rectOf(shell(page).panel);
    const footer = await rectOf(shell(page).footer);

    expect(text.top, 'the headline sits under the camera').toBeGreaterThanOrEqual(camera.bottom - 1);
    expect(text.left, 'the headline starts in the camera column').toBeGreaterThanOrEqual(camera.left - 1);
    expect(text.right, 'the headline stays left of the panel').toBeLessThanOrEqual(panel.left);
    expect(text.bottom, 'the headline sits above the footer').toBeLessThanOrEqual(footer.top);
    expect(await fontPx(headline), 'the headline font size').toBeGreaterThanOrEqual(28);
  });

  test('keeps the camera box the same size from idle into the setup check', async ({ page }) => {
    await page.clock.install();
    const backend = await MockBackend.attach(page);
    await openGuidedRun(page);
    await expect(idleHeadline(page)).toBeVisible();
    const idle = await rectOf(guidedPage(page).cameraBox);

    await guidedPage(page).start.click();
    await expect.poll(() => backend.frames.length).toBeGreaterThan(1);
    await expect(idleHeadline(page)).toHaveCount(0);

    const checking = await rectOf(guidedPage(page).cameraBox);
    expect(Math.abs(checking.top - idle.top), 'camera top').toBeLessThanOrEqual(1);
    expect(Math.abs(checking.bottom - idle.bottom), 'camera bottom').toBeLessThanOrEqual(1);
    expect(Math.abs(checking.left - idle.left), 'camera left').toBeLessThanOrEqual(1);
    expect(Math.abs(checking.right - idle.right), 'camera right').toBeLessThanOrEqual(1);
  });

  test('shows the plan with no empty result tiles anywhere in idle', async ({ page }) => {
    await openIdle(page);
    const guided = guidedPage(page);

    await expect(guided.headline(PLAN_TITLE)).toBeVisible();
    await expect(guided.main.getByText('Leave your watch alone during the run. Check its history afterwards.')).toBeVisible();
    await expectNoResultTiles(page);
  });

  test('shows the idle headline and the hidden camera label in idle only', async ({ page }) => {
    const backend = await MockBackend.attach(page);
    await page.clock.install();
    await startCheck(page, backend);

    await expect(idleHeadline(page)).toHaveCount(0);
    await expect(guidedPage(page).main.getByText(IDLE_CAMERA_LABEL, { exact: true })).toHaveCount(0);
  });

  test('shows no idle headline on the result', async ({ page }) => {
    await reachResult(page, RANGED_READING);

    await expect(guidedPage(page).headline('Done. Nice sitting.')).toBeVisible();
    await expect(page.getByText(IDLE_HEADLINE, { exact: true })).toHaveCount(0);
  });
});

test.describe('the quiet idle page on a phone', () => {
  test.use({ viewport: PHONE });

  test('puts the idle headline under the empty camera box and above the plan', async ({ page }) => {
    await openIdle(page);
    const headline = idleHeadline(page);
    await expect(headline).toBeVisible();

    const camera = await rectOf(guidedPage(page).cameraBox);
    const text = await rectOf(headline);
    const plan = await rectOf(guidedPage(page).headline(PLAN_TITLE));

    expect(text.top, 'the headline sits under the camera').toBeGreaterThanOrEqual(camera.bottom - 1);
    expect(text.bottom, 'the headline sits above the plan').toBeLessThanOrEqual(plan.top + 1);
    expect(await drawnTexts(guidedPage(page).cameraBox), 'words drawn on the idle camera box').toEqual([]);
    await expectNoResultTiles(page);
  });
});

test.describe('the quiet error state on a desktop', () => {
  test.use({ viewport: DESKTOP });

  test('shows only the alert in the side panel and no empty tiles when the camera is refused', async ({ page }) => {
    await reachCameraDenied(page);
    const guided = guidedPage(page);

    await expect(guided.alert).toBeVisible();
    expect(await drawnTexts(shell(page).panel, true), 'words in the side panel outside the alert').toEqual([]);
    await expectNoResultTiles(page);
    await expect(idleHeadline(page)).toHaveCount(0);
    await expect(guided.main.getByText("Camera's off. The browser said no.", { exact: true })).toBeVisible();
    expect(await drawnTexts(guided.cameraBox), 'words drawn on the camera box').toEqual([
      "Camera's off. The browser said no.",
    ]);
  });

  test('shows only the alert and keeps the camera line when the camera drops out in the warm-up', async ({ page }) => {
    await reachCameraLostInWarmUp(page);
    const guided = guidedPage(page);

    await expect(guided.alert).toBeVisible();
    expect(await drawnTexts(shell(page).panel, true), 'words in the side panel outside the alert').toEqual([]);
    await expectNoResultTiles(page);
    await expect(idleHeadline(page)).toHaveCount(0);
    await expect(guided.cameraBox.getByText(CAMERA_DROPPED_LINE, { exact: true })).toBeVisible();
    expect(await drawnTexts(guided.cameraBox), 'words drawn on the camera box').toEqual([CAMERA_DROPPED_LINE]);
  });

  test('shows no empty result tiles after Stop', async ({ page }) => {
    const backend = await MockBackend.attach(page);
    const guided = guidedPage(page);
    await startRun(page, backend);
    await advanceRun(page, backend, 10000, 2500);

    await guided.stop.click();

    await expect(guided.main.getByText(RUN_STOPPED_TEXT, { exact: true })).toBeVisible();
    await expectNoResultTiles(page);
  });
});

test.describe('the quiet error state on a phone', () => {
  test.use({ viewport: PHONE });

  test('puts the alert first, above the camera box, on the first screen', async ({ page }) => {
    await reachCameraLostInWarmUp(page);
    const guided = guidedPage(page);
    await scrollPageToTop(page);

    await expect(guided.alert).toBeInViewport({ ratio: 1 });
    await expect
      .poll(async () => {
        const bar = await barRect(page);
        const alert = await rectOf(guided.alert);
        return bar === null ? 'no bottom bar' : alert.bottom <= bar.top;
      }, { message: 'the alert ends above the bottom bar' })
      .toBe(true);
    const alert = await rectOf(guided.alert);
    const camera = await rectOf(guided.cameraBox);
    expect(alert.bottom, 'the alert comes before the camera box').toBeLessThanOrEqual(camera.top);
    await expectNoResultTiles(page);
  });

  test('puts the camera refused alert above the camera box with no empty tiles', async ({ page }) => {
    await reachCameraDenied(page);
    await scrollPageToTop(page);

    const alert = await rectOf(guidedPage(page).alert);
    const camera = await rectOf(guidedPage(page).cameraBox);

    expect(alert.bottom, 'the alert comes before the camera box').toBeLessThanOrEqual(camera.top);
    await expectNoResultTiles(page);
  });
});

const EXPLAINER_COUNTS: Array<{ state: GuidedState; count: number }> = [
  { state: 'idle', count: 0 },
  { state: 'check', count: 1 },
  { state: 'warm-up', count: 1 },
  { state: 'counting', count: 1 },
  { state: 'result', count: 1 },
  { state: 'no-reading', count: 0 },
  { state: 'camera-denied', count: 0 },
];

const PHONE_EXPLAINER_STATES = new Set<GuidedState>(['counting', 'result', 'no-reading']);

for (const viewport of [
  { name: 'desktop', size: DESKTOP, states: EXPLAINER_COUNTS },
  {
    name: 'phone',
    size: PHONE,
    states: EXPLAINER_COUNTS.filter(({ state }) => PHONE_EXPLAINER_STATES.has(state)),
  },
] as const) {
  test.describe(`the ms explainer on a ${viewport.name}`, () => {
    test.use({ viewport: viewport.size });

    for (const { state, count } of viewport.states) {
      test(`shows the ms explainer ${count === 1 ? 'once' : 'nowhere'} in the ${state} state`, async ({ page }) => {
        await reachState(page, state);

        await expect(page.getByText(VARIATION_LINE, { exact: true })).toHaveCount(count);
        await expect(page.getByText(/in ms \(thousandths of a second\)/)).toHaveCount(count);
      });
    }
  });
}

test.describe('the privacy sentence', () => {
  test.use({ viewport: DESKTOP });

  test('sits only in Settings on the idle page', async ({ page }) => {
    await openIdle(page);

    await expect(page.getByText(PRIVACY_SENTENCE, { exact: true })).toHaveCount(0);
    await openSettings(page);
    await expect(page.getByText(PRIVACY_SENTENCE, { exact: true })).toHaveCount(1);
    await expect(settingsPanel(page).privacy).toBeVisible();
  });

  test('sits only in Settings on the result', async ({ page }) => {
    await reachResult(page, RANGED_READING);

    await expect(page.getByText(PRIVACY_SENTENCE, { exact: true })).toHaveCount(0);
    await openSettings(page);
    await expect(page.getByText(PRIVACY_SENTENCE, { exact: true })).toHaveCount(1);
    await expect(settingsPanel(page).privacy).toBeVisible();
  });
});

test.describe('the privacy sentence on a phone', () => {
  test.use({ viewport: PHONE });

  test('sits only in the Settings sheet on the result', async ({ page }) => {
    await reachResult(page, RANGED_READING);
    await scrollPageToTop(page);

    await expect(page.getByText(PRIVACY_SENTENCE, { exact: true })).toHaveCount(0);
    await openSettings(page);
    await expect(page.getByText(PRIVACY_SENTENCE, { exact: true })).toHaveCount(1);
    await expect(settingsPanel(page).privacy).toBeVisible();
  });
});
