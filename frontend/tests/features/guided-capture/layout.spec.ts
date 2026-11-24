import { expect, test } from '@playwright/test';
import { fontFamily, guidedPage, openGuidedRun, pushAndConfirm, startRun } from '../../support/guided-page';
import { MockBackend } from '../../support/mock-backend';
import { boxOf } from '../../support/monitor-page';

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
      const steps = await boxOf(guided.panel.getByRole('list', { name: 'Capture steps' }));
      const card = await boxOf(guided.panel);

      expect(button.y + button.height).toBeLessThanOrEqual(steps.y);
      expect(button.x + button.width).toBeGreaterThanOrEqual(card.x + card.width * 0.75);
    });
  });
});
