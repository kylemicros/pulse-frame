import { expect, test } from '@playwright/test';
import { CAMERA_STATES, reachState, startRunAt } from '../../support/app-shell';
import { guidedPage, openGuidedRun } from '../../support/guided-page';
import { MockBackend } from '../../support/mock-backend';
import { boxOf } from '../../support/page-helpers';
import { finishResultRun, RANGED_READING } from '../../support/result-states';
import { buttonLook, focusRing, LOCK_WORDS, tabTo, underAriaHidden } from '../../support/settings';

const CORNER_PX = 24;
const TARGET_PX = 44;

test.describe('the privacy lock on the camera on a desktop', () => {
  test.use({ viewport: { width: 1280, height: 800 } });

  test('puts a 44 px lock button named Stays on this computer at the camera top left corner', async ({ page }) => {
    await MockBackend.attach(page);
    const guided = guidedPage(page);
    await openGuidedRun(page);

    await expect(guided.lock).toBeVisible();
    await expect(guided.lock).toHaveAccessibleName(LOCK_WORDS);
    const lock = await boxOf(guided.lock);
    const camera = await boxOf(guided.video);

    expect(lock.width).toBeGreaterThanOrEqual(TARGET_PX);
    expect(lock.height).toBeGreaterThanOrEqual(TARGET_PX);
    expect(lock.x - camera.x, 'lock from the camera left edge').toBeGreaterThanOrEqual(0);
    expect(lock.x - camera.x, 'lock from the camera left edge').toBeLessThanOrEqual(CORNER_PX);
    expect(lock.y - camera.y, 'lock from the camera top edge').toBeGreaterThanOrEqual(0);
    expect(lock.y - camera.y, 'lock from the camera top edge').toBeLessThanOrEqual(CORNER_PX);
  });

  test('shows only the outlined lock at rest, its words not drawn', async ({ page }) => {
    await MockBackend.attach(page);
    const guided = guidedPage(page);
    await openGuidedRun(page);
    await page.mouse.move(0, 0);

    await expect(guided.lock).toBeVisible();
    await expect(guided.lock.locator('svg')).toHaveCount(1);
    await expect(guided.lockWords).toBeHidden();
  });

  test('shows its words on hover, keeps them while the pointer moves onto them, and hides them once it leaves', async ({
    page,
  }) => {
    await MockBackend.attach(page);
    const guided = guidedPage(page);
    await openGuidedRun(page);
    await expect(guided.lock).toBeVisible();

    await guided.lock.hover();

    await expect(guided.lockWords).toBeVisible();
    expect(await underAriaHidden(guided.lockWords), 'the drawn words are read a second time').toBe(true);

    await guided.lockWords.hover();

    await expect(guided.lockWords).toBeVisible();

    await page.mouse.move(640, 790);

    await expect(guided.lockWords).toBeHidden();
  });

  test('hides the hover words with Escape while the pointer stays on the lock', async ({ page }) => {
    await MockBackend.attach(page);
    const guided = guidedPage(page);
    await openGuidedRun(page);
    await expect(guided.lock).toBeVisible();
    await guided.lock.hover();
    await expect(guided.lockWords).toBeVisible();

    await page.keyboard.press('Escape');

    await expect(guided.lockWords).toBeHidden();
  });

  test('shows its words on keyboard focus with a focus ring, and Escape hides them with focus staying on the lock', async ({
    page,
  }) => {
    await MockBackend.attach(page);
    const guided = guidedPage(page);
    await openGuidedRun(page);
    await page.mouse.move(0, 0);

    await tabTo(page, guided.lock);

    await expect(guided.lockWords).toBeVisible();
    const ring = await focusRing(guided.lock);
    expect(
      (ring.outlineStyle !== 'none' && ring.outlineWidth >= 2) || ring.shadow !== 'none',
      `focus ring ${JSON.stringify(ring)}`,
    ).toBe(true);

    await page.keyboard.press('Escape');

    await expect(guided.lockWords).toBeHidden();
    await expect(guided.lock).toBeFocused();
  });

  test('changes the lock colour on hover and never its backdrop', async ({ page }) => {
    await MockBackend.attach(page);
    const guided = guidedPage(page);
    await openGuidedRun(page);
    await page.mouse.move(0, 0);
    await expect(guided.lock).toBeVisible();
    const resting = await buttonLook(guided.lock);

    await guided.lock.hover();

    const hovered = await buttonLook(guided.lock);
    expect(hovered.iconColour, 'the lock colour on hover').not.toBe(resting.iconColour);
    expect(hovered.background, 'the backdrop on hover').toBe(resting.background);
    expect(hovered.shadow, 'the shadow on hover').toBe(resting.shadow);
  });

  test('does not show the lock words after Start again when they were open from the keyboard as the run ended', async ({
    page,
  }) => {
    const guided = guidedPage(page);
    const backend = await startRunAt(page, '/');
    await page.mouse.move(0, 0);
    await tabTo(page, guided.lock);
    await expect(guided.lockWords).toBeVisible();

    await finishResultRun(page, backend, RANGED_READING);

    await expect(guided.lock).toBeHidden();
    await expect(guided.startAgain).toBeFocused();
    const framesBefore = backend.frames.length;

    await page.keyboard.press('Enter');

    await expect.poll(() => backend.frames.length).toBeGreaterThan(framesBefore + 1);
    await expect(guided.lock).toBeVisible();
    await expect(guided.lockWords).toBeHidden();
  });

  for (const state of CAMERA_STATES) {
    test(`shows the lock on the camera in the ${state} state`, async ({ page }) => {
      await reachState(page, state);
      const guided = guidedPage(page);

      await expect(guided.lock).toBeVisible();
      const lock = await boxOf(guided.lock);
      const camera = await boxOf(guided.video);
      expect(lock.x - camera.x, 'lock from the camera left edge').toBeGreaterThanOrEqual(0);
      expect(lock.x - camera.x, 'lock from the camera left edge').toBeLessThanOrEqual(CORNER_PX);
      expect(lock.y - camera.y, 'lock from the camera top edge').toBeGreaterThanOrEqual(0);
      expect(lock.y - camera.y, 'lock from the camera top edge').toBeLessThanOrEqual(CORNER_PX);
    });
  }
});

test.describe('the privacy lock on a touch phone', () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true });

  test('shows its words on a tap and hides them on a second tap', async ({ page }) => {
    await MockBackend.attach(page);
    const guided = guidedPage(page);
    await openGuidedRun(page);
    await expect(guided.lock).toBeVisible();
    await expect(guided.lockWords).toBeHidden();

    await guided.lock.tap();

    await expect(guided.lockWords).toBeVisible();

    await guided.lock.tap();

    await expect(guided.lockWords).toBeHidden();
  });

  test('does not show the lock words after Start again when they were open from a tap as the run ended', async ({
    page,
  }) => {
    const guided = guidedPage(page);
    const backend = await startRunAt(page, '/');
    await guided.lock.tap();
    await expect(guided.lockWords).toBeVisible();

    await finishResultRun(page, backend, RANGED_READING);

    await expect(guided.lock).toBeHidden();
    await expect(guided.startAgain).toBeFocused();
    const framesBefore = backend.frames.length;

    await page.keyboard.press('Enter');

    await expect.poll(() => backend.frames.length).toBeGreaterThan(framesBefore + 1);
    await expect(guided.lock).toBeVisible();
    await expect(guided.lockWords).toBeHidden();
  });

  test('hides the tapped words on a tap anywhere else', async ({ page }) => {
    await MockBackend.attach(page);
    const guided = guidedPage(page);
    await openGuidedRun(page);
    await expect(guided.lock).toBeVisible();
    await guided.lock.tap();
    await expect(guided.lockWords).toBeVisible();

    await guided.headline('Two and a half minutes, mostly doing nothing.').tap();

    await expect(guided.lockWords).toBeHidden();
  });
});
