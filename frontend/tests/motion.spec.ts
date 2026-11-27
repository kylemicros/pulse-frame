import { expect, test, type Page } from '@playwright/test';
import { EARLIER, rectOf, startRunAt, type Rect } from './support/app-shell';
import {
  advanceRun,
  advanceRunUntil,
  guidedPage,
  openGuidedRun,
  passSetupCheck,
  pushAndConfirm,
  setHrvAndConfirm,
  startCheck,
} from './support/guided-page';
import { MockBackend } from './support/mock-backend';
import {
  clearMotion,
  expectFade,
  isFade,
  type Motion,
  motionSeen,
  movingParts,
  PHASE_FADE_MS,
  QUICK_FADE_MS,
  recordMotion,
  scalesOrTurns,
  SHEET_SLIDE_MS,
  shiftY,
  slides,
} from './support/motion';
import { RANGED_READING, resultHero } from './support/result-states';
import { settingsPanel } from './support/settings';

const DESKTOP = { width: 1280, height: 800 } as const;
const PHONE = { width: 390, height: 844 } as const;
const WARM_UP_HEADLINE = 'Stay in frame. No need to watch.';
const COUNTING_HEADLINE = 'Counting. Hold still.';
const NEAR_COUNTING_MS = 55000;
const NEAR_DONE_MS = 20000;
const CLOSE_SLICE_MS = 1000;
const SAME_SPOT_PX = 1;

async function reachCountingStart(page: Page): Promise<void> {
  const backend = await startRunAt(page, '/');
  const guided = guidedPage(page);
  await expect(guided.warmUpTimer).toBeVisible();
  await pushAndConfirm(page, backend, { bpm: 68.2, quality_db: 9.4, state: 'ok' });
  await advanceRun(page, backend, NEAR_COUNTING_MS);
  await expect(guided.warmUpTimer).toBeVisible();
  await clearMotion(page);
  await advanceRunUntil(page, backend, guided.countedTimer, CLOSE_SLICE_MS);
  await expect(guided.headline(COUNTING_HEADLINE)).toBeVisible();
}

async function reachWarmUpStart(page: Page): Promise<void> {
  const backend = await MockBackend.attach(page);
  await page.clock.install();
  await startCheck(page, backend);
  const guided = guidedPage(page);
  await expect(guided.headline('Quick setup check')).toBeVisible();
  await clearMotion(page);
  await passSetupCheck(page, backend);
  await expect(guided.headline(WARM_UP_HEADLINE)).toBeVisible();
}

async function reachResultEnd(page: Page): Promise<Rect> {
  const backend = await startRunAt(page, '/');
  const guided = guidedPage(page);
  await pushAndConfirm(page, backend, { bpm: 68.2, quality_db: 9.4, state: 'ok' });
  await advanceRunUntil(page, backend, guided.countedTimer);
  const camera = await rectOf(guided.cameraBox);
  await setHrvAndConfirm(page, backend, EARLIER);
  await advanceRun(page, backend, 60000);
  await setHrvAndConfirm(page, backend, RANGED_READING);
  await advanceRun(page, backend, NEAR_DONE_MS);
  await expect(guided.countedTimer).toBeVisible();
  await clearMotion(page);
  await advanceRunUntil(page, backend, guided.startAgain, CLOSE_SLICE_MS);
  await expect(resultHero(page).hero).toBeVisible();
  return camera;
}

function rising(seen: Motion[]): Motion[] {
  return seen.filter((motion) => motion.tag === 'settings' && shiftY(motion) > 0.5);
}

async function openIdle(page: Page): Promise<void> {
  await MockBackend.attach(page);
  await openGuidedRun(page);
  await expect(guidedPage(page).start).toBeVisible();
  await page.mouse.move(0, 0);
  await clearMotion(page);
}

test.describe('motion on a desktop', () => {
  test.use({ viewport: DESKTOP });

  test.beforeEach(async ({ page }) => {
    await recordMotion(page);
  });

  test('cross-fades the panel in 180 ms, opacity only, when counting starts, while the stepper and the strip switch at once', async ({
    page,
  }) => {
    await reachCountingStart(page);

    const fades = await expectFade(page, 'panel', PHASE_FADE_MS, COUNTING_HEADLINE);
    expect(fades.filter(slides), 'panel fades that slide').toEqual([]);
    const seen = await motionSeen(page);
    expect(movingParts(seen, ['banner', 'strip']), 'motion on the stepper or the phase strip').toEqual([]);
    expect(seen.filter(scalesOrTurns), 'motion that scales or turns').toEqual([]);
    expect(seen.filter((motion) => motion.iterations !== 1), 'motion that repeats').toEqual([]);
  });

  test('cross-fades the panel in 180 ms, opacity only, when the warm-up starts after the setup check', async ({ page }) => {
    await reachWarmUpStart(page);

    const fades = await expectFade(page, 'panel', PHASE_FADE_MS, WARM_UP_HEADLINE);
    expect(fades.filter(slides), 'panel fades that slide').toEqual([]);
    const seen = await motionSeen(page);
    expect(movingParts(seen, ['banner', 'strip']), 'motion on the stepper or the phase strip').toEqual([]);
    expect(seen.filter(scalesOrTurns), 'motion that scales or turns').toEqual([]);
  });

  test('fades the camera out and the result card in, 180 ms each, in the same spot with no zoom, the lock out of reach from the start', async ({
    page,
  }) => {
    const camera = await reachResultEnd(page);

    const cardFades = await expectFade(page, 'result', PHASE_FADE_MS);
    const cameraFades = await expectFade(page, 'camera', PHASE_FADE_MS);
    expect(
      cardFades.some((fade) => fade.endOpacity > fade.midOpacity),
      'the result card fades in',
    ).toBe(true);
    expect(
      cameraFades.some((fade) => fade.endOpacity < fade.midOpacity),
      'the camera fades out',
    ).toBe(true);
    expect([...cardFades, ...cameraFades].filter(slides), 'result fades that slide').toEqual([]);
    expect(
      cameraFades.filter((fade) => !fade.lockHidden),
      'camera fades that began with the lock still in the accessibility tree',
    ).toEqual([]);
    await expect(guidedPage(page).lock).toHaveCount(0);
    const card = await rectOf(resultHero(page).hero);
    expect(Math.abs(card.top - camera.top), 'the card top against the camera top').toBeLessThanOrEqual(SAME_SPOT_PX);
    expect(Math.abs(card.left - camera.left), 'the card left against the camera left').toBeLessThanOrEqual(SAME_SPOT_PX);
  });

  test('fades the lock words in over 120 ms, opacity only', async ({ page }) => {
    const guided = guidedPage(page);
    await openIdle(page);

    await guided.lock.hover();

    await expect(guided.lockWords).toBeVisible();
    const fades = await expectFade(page, 'lockWords', QUICK_FADE_MS);
    expect(fades.filter(slides), 'lock word fades that slide').toEqual([]);
  });

  test('fades the Settings popover in over 120 ms, opacity only', async ({ page }) => {
    const settings = settingsPanel(page);
    await openIdle(page);

    await settings.gear.click();

    await expect(settings.dialog).toBeVisible();
    const fades = await expectFade(page, 'settings', QUICK_FADE_MS);
    expect(fades.filter(slides), 'popover fades that slide').toEqual([]);
    expect(movingParts(await motionSeen(page), ['settings']).filter(slides), 'popover parts that slide').toEqual([]);
  });
});

test.describe('motion on a phone', () => {
  test.use({ viewport: PHONE });

  test.beforeEach(async ({ page }) => {
    await recordMotion(page);
  });

  test('slides the Settings sheet up over 180 ms with the scrim fading in, nothing scaling', async ({ page }) => {
    const settings = settingsPanel(page);
    await openIdle(page);

    await settings.gear.click();

    await expect(settings.dialog).toBeVisible();
    await expect.poll(async () => rising(await motionSeen(page)).length, { message: 'the sheet slides up' }).toBeGreaterThan(0);
    const seen = await motionSeen(page);
    for (const slide of rising(seen)) {
      expect(slide.durationMs, 'the sheet slide lasts').toBe(SHEET_SLIDE_MS);
      expect(scalesOrTurns(slide), `the sheet slide scales: ${JSON.stringify(slide)}`).toBe(false);
    }
    const scrimFades = seen.filter((motion) => motion.tag === 'scrim' && isFade(motion));
    expect(scrimFades.length, 'the scrim fades in').toBeGreaterThan(0);
    for (const fade of scrimFades) {
      expect(fade.durationMs, 'the scrim fade lasts').toBeGreaterThan(0);
      expect(fade.durationMs, 'the scrim fade lasts').toBeLessThanOrEqual(SHEET_SLIDE_MS);
    }
    expect(seen.filter(scalesOrTurns), 'motion that scales or turns').toEqual([]);
  });
});

test.describe('motion under reduced motion on a desktop', () => {
  test.use({ viewport: DESKTOP, reducedMotion: 'reduce' });

  test.beforeEach(async ({ page }) => {
    await recordMotion(page);
  });

  test('swaps the panel at once when counting starts under reduced motion', async ({ page }) => {
    await reachCountingStart(page);

    expect(movingParts(await motionSeen(page), ['panel', 'banner', 'strip', 'camera']), 'motion left').toEqual([]);
  });

  test('swaps the camera for the result card at once under reduced motion', async ({ page }) => {
    await reachResultEnd(page);

    expect(movingParts(await motionSeen(page), ['panel', 'camera', 'result', 'banner']), 'motion left').toEqual([]);
  });

  test('shows the lock words and the Settings popover at once under reduced motion', async ({ page }) => {
    const guided = guidedPage(page);
    const settings = settingsPanel(page);
    await openIdle(page);

    await guided.lock.hover();
    await expect(guided.lockWords).toBeVisible();
    await page.mouse.move(0, 0);
    await settings.gear.click();
    await expect(settings.dialog).toBeVisible();

    expect(movingParts(await motionSeen(page), ['lockWords', 'camera', 'settings', 'banner']), 'motion left').toEqual([]);
  });
});

test.describe('motion under reduced motion on a phone', () => {
  test.use({ viewport: PHONE, reducedMotion: 'reduce' });

  test.beforeEach(async ({ page }) => {
    await recordMotion(page);
  });

  test('shows the Settings sheet and its scrim at once under reduced motion', async ({ page }) => {
    const settings = settingsPanel(page);
    await openIdle(page);

    await settings.gear.click();

    await expect(settings.dialog).toBeVisible();
    expect(movingParts(await motionSeen(page), ['settings', 'scrim']), 'motion left').toEqual([]);
  });
});
