import { expect, test } from '@playwright/test';
import { guidedPage } from './support/guided-page';
import { MockBackend } from './support/mock-backend';
import { cameraTrackStates, monitorPage, spyOnCamera, startMonitoring } from './support/monitor-page';

test.describe('page tabs', () => {
  test('shows the Live monitor and Guided run tabs with the live monitor chosen first', async ({ page }) => {
    const guided = guidedPage(page);
    const monitor = monitorPage(page);

    await page.goto('/');

    await expect(page.getByRole('tab')).toHaveCount(2);
    await expect(guided.liveTab).toHaveAttribute('aria-selected', 'true');
    await expect(guided.guidedTab).toHaveAttribute('aria-selected', 'false');
    await expect(page.getByRole('tabpanel', { name: 'Live monitor' })).toBeVisible();
    await expect(monitor.start).toBeVisible();
    await expect(guided.panel).toBeHidden();
    await expect(page).toHaveTitle('pulse-frame');
  });

  test('opens the guided run when its tab is clicked and hides the live monitor', async ({ page }) => {
    const guided = guidedPage(page);

    await page.goto('/');
    await guided.guidedTab.click();

    await expect(guided.guidedTab).toHaveAttribute('aria-selected', 'true');
    await expect(guided.panel).toBeVisible();
    await expect(page.getByRole('tabpanel', { name: 'Live monitor' })).toBeHidden();
    await expect(monitorPage(page).heartRate).toBeHidden();
    await expect(page.getByRole('button', { name: 'Start', exact: true })).toHaveCount(1);
  });

  test('gives the guided run a main landmark and one level 1 heading', async ({ page }) => {
    const guided = guidedPage(page);

    await page.goto('/');
    await guided.guidedTab.click();
    await expect(guided.panel).toBeVisible();

    await expect(page.getByRole('main')).toHaveCount(1);
    await expect(page.getByRole('main')).toBeVisible();
    await expect(page.getByRole('heading', { level: 1 })).toHaveCount(1);
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
  });

  test('ends a live monitor session, its camera and its socket when the Guided run tab is chosen', async ({ page }) => {
    await spyOnCamera(page);
    const backend = await MockBackend.attach(page);
    const guided = guidedPage(page);

    await startMonitoring(page, backend);
    await guided.guidedTab.click();

    await expect(guided.panel).toBeVisible();
    await expect.poll(async () => (await cameraTrackStates(page)).length).toBeGreaterThan(0);
    await expect.poll(async () => (await cameraTrackStates(page)).every((state) => state === 'ended')).toBe(true);
    await expect.poll(() => backend.openConnections().length).toBe(0);
    await expect(guided.start).toBeVisible();
  });

  test('moves between the tabs with the arrow keys', async ({ page }) => {
    const guided = guidedPage(page);

    await page.goto('/');
    await guided.liveTab.focus();
    await page.keyboard.press('ArrowRight');
    await expect(guided.guidedTab).toBeFocused();
    await page.keyboard.press('Enter');

    await expect(guided.panel).toBeVisible();
    await page.keyboard.press('ArrowLeft');
    await expect(guided.liveTab).toBeFocused();
  });

  test('keeps the live monitor working after a visit to the guided run', async ({ page }) => {
    const backend = await MockBackend.attach(page);
    const guided = guidedPage(page);
    const monitor = monitorPage(page);

    await page.goto('/');
    await guided.guidedTab.click();
    await expect(guided.panel).toBeVisible();
    await guided.liveTab.click();
    await monitor.start.click();
    await expect.poll(() => backend.frames.length).toBeGreaterThan(1);
    backend.pushReading({ bpm: 71.8, quality_db: 9.2, state: 'ok' });

    await expect(monitor.bpmValue).toHaveText(/^(71\.8|72)$/);
  });
});
