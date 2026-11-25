import { expect, test, type Page } from '@playwright/test';
import { fontFamily, guidedPage, openGuidedRun, pushAndConfirm, startRun } from '../../support/guided-page';
import { MockBackend } from '../../support/mock-backend';
import { boxOf } from '../../support/page-helpers';

const PAGE_BACKGROUND = { light: 'rgb(247, 247, 245)', dark: 'rgb(20, 20, 20)' } as const;

function backgroundBehind(page: Page, x: number, y: number): Promise<string> {
  return page.evaluate(
    ([left, top]) => {
      for (let node = document.elementFromPoint(left, top); node !== null; node = node.parentElement) {
        const colour = getComputedStyle(node).backgroundColor;
        if (colour !== 'rgba(0, 0, 0, 0)' && colour !== 'transparent') {
          return colour;
        }
      }
      return getComputedStyle(document.documentElement).backgroundColor;
    },
    [x, y],
  );
}

test.describe('the guided run as the only page', () => {
  test('shows one main landmark, the brand as the one level 1 heading, and no tabs', async ({ page }) => {
    await MockBackend.attach(page);
    const guided = guidedPage(page);

    await openGuidedRun(page);

    await expect(page.getByRole('main')).toHaveCount(1);
    await expect(page.getByRole('main')).toBeVisible();
    await expect(page.getByRole('heading', { level: 1 })).toHaveCount(1);
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('pulse-frame');
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
    await expect(page.getByRole('tablist')).toHaveCount(0);
    await expect(page.getByRole('tab')).toHaveCount(0);
    await expect(page.getByRole('tabpanel')).toHaveCount(0);
    await expect(page.getByText('Live monitor')).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Start', exact: true })).toHaveCount(1);
    await expect(guided.start).toBeVisible();
    await expect(page).toHaveTitle('pulse-frame');
  });

  for (const colorScheme of ['light', 'dark'] as const) {
    test(`fills the page with the ${colorScheme} page background from the first load`, async ({ page }) => {
      await page.emulateMedia({ colorScheme });
      await MockBackend.attach(page);
      const viewport = page.viewportSize();
      expect(viewport).not.toBeNull();

      await openGuidedRun(page);

      expect(await backgroundBehind(page, 2, (viewport?.height ?? 0) - 2)).toBe(PAGE_BACKGROUND[colorScheme]);
      expect(await backgroundBehind(page, (viewport?.width ?? 0) - 2, 2)).toBe(PAGE_BACKGROUND[colorScheme]);
    });
  }
});

test.describe('guided run layout', () => {
  test('sets prose in the system sans and numbers in JetBrains Mono', async ({ page }) => {
    await page.clock.install();
    const backend = await MockBackend.attach(page);
    const guided = guidedPage(page);
    await startRun(page, backend);
    await pushAndConfirm(page, backend, { bpm: 66.6, quality_db: 9.0, state: 'ok' });

    const headline = await fontFamily(guided.headline('Stay in frame. No need to watch.'));
    const number = await fontFamily(guided.liveReadings.getByText(/^67$|^66\.6$/));
    const countdown = await fontFamily(guided.warmUpTimer);

    expect(headline).not.toMatch(/JetBrains Mono/);
    expect(headline).toMatch(/system-ui|ui-sans-serif|sans-serif/);
    expect(number).toMatch(/^"?JetBrains Mono/);
    expect(countdown).toMatch(/^"?JetBrains Mono/);
  });

  test.describe('on a phone', () => {
    test.use({ viewport: { width: 390, height: 844 } });

    test('keeps the main button as a full-width bar at the bottom of the screen', async ({ page }) => {
      await MockBackend.attach(page);
      const guided = guidedPage(page);
      await openGuidedRun(page);

      const button = await boxOf(guided.start);

      expect(button.width).toBeGreaterThanOrEqual(390 * 0.85);
      expect(button.y + button.height).toBeGreaterThanOrEqual(844 - 32);
      expect(button.y + button.height).toBeLessThanOrEqual(844);
    });
  });

  test.describe('on a desktop', () => {
    test.use({ viewport: { width: 1280, height: 800 } });

    test('keeps the main button top right of the card, above the steps', async ({ page }) => {
      await MockBackend.attach(page);
      const guided = guidedPage(page);
      await openGuidedRun(page);

      const button = await boxOf(guided.start);
      const steps = await boxOf(guided.main.getByRole('list', { name: 'Capture steps' }));
      const card = await boxOf(guided.main);

      expect(button.y + button.height).toBeLessThanOrEqual(steps.y);
      expect(button.x + button.width).toBeGreaterThanOrEqual(card.x + card.width * 0.75);
    });
  });
});
