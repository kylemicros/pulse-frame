import { expect, test } from '@playwright/test';
import { expectCurrentStep, guidedPage, openGuidedRun } from '../../support/guided-page';
import { MockBackend } from '../../support/mock-backend';
import { openSettings, settingsPanel } from '../../support/settings';
import { cameraCalls, holdCamera, releaseCamera, spyOnCamera, videoIsPlaying } from '../../support/page-helpers';
import { expectNoResultTiles, idleHeadline, OLD_IDLE_CAMERA_LINE } from '../../support/result-states';

test.describe('guided run before Start', () => {
  test('shows the idle page with step 1 current, the plan, the idle headline and no empty readings', async ({
    page,
  }) => {
    await MockBackend.attach(page);
    const guided = guidedPage(page);

    await openGuidedRun(page);

    await expectCurrentStep(page, 'Get comfy');
    await expect(guided.step('Warm-up')).toContainText('60 s');
    await expect(guided.step('Counted')).toContainText('90 s');
    await expect(guided.headline('Two and a half minutes, mostly doing nothing.')).toBeVisible();
    await expect(idleHeadline(page)).toBeVisible();
    await expect(guided.main.getByText(OLD_IDLE_CAMERA_LINE)).toHaveCount(0);
    await expectNoResultTiles(page);
    await expect(guided.disclaimer).toBeVisible();
    await expect(guided.start).toBeVisible();
    await expect(guided.stop).toHaveCount(0);
  });

  test('has the Chime switch on by default in Settings and turns it off and on', async ({ page }) => {
    await MockBackend.attach(page);
    const settings = settingsPanel(page);

    await openGuidedRun(page);
    await openSettings(page);

    await expect(settings.chime).toBeChecked();
    await expect(settings.chime.getByText('On', { exact: true })).toBeVisible();
    await settings.chime.click();
    await expect(settings.chime).not.toBeChecked();
    await expect(settings.chime.getByText('Off', { exact: true })).toBeVisible();
    await settings.chime.click();
    await expect(settings.chime).toBeChecked();
  });

  test('says the camera is waking up while it starts, then shows the camera', async ({ page }) => {
    await holdCamera(page);
    const backend = await MockBackend.attach(page);
    const guided = guidedPage(page);
    const waking = guided.main.getByText('Waking up the camera. Give it a second.', { exact: true });
    await openGuidedRun(page);
    await expect(waking).toHaveCount(0);

    await guided.start.click();

    await expect(waking).toBeVisible();
    await expect(guided.main.getByText(OLD_IDLE_CAMERA_LINE)).toHaveCount(0);

    await releaseCamera(page);

    await expect.poll(() => videoIsPlaying(guided.video)).toBe(true);
    await expect.poll(() => backend.frames.length).toBeGreaterThan(1);
    await expect(waking).toHaveCount(0);
  });

  test('opens no camera and no socket until Start is clicked', async ({ page }) => {
    await spyOnCamera(page);
    const backend = await MockBackend.attach(page);
    const guided = guidedPage(page);

    await openGuidedRun(page);
    await expect(guided.start).toBeVisible();

    expect(await cameraCalls(page)).toBe(0);
    expect(backend.connections).toEqual([]);

    await guided.start.click();

    await expect.poll(() => cameraCalls(page)).toBe(1);
    await expect.poll(() => backend.frames.length).toBeGreaterThan(1);
    await expect.poll(() => videoIsPlaying(guided.main.getByLabel('Camera preview'))).toBe(true);
    await expect(guided.stop).toBeVisible();
  });
});
