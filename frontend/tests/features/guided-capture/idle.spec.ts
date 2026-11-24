import { expect, test } from '@playwright/test';
import { expectCurrentStep, guidedPage, openGuidedRun } from '../../support/guided-page';
import { MockBackend } from '../../support/mock-backend';
import { cameraCalls, spyOnCamera, videoIsPlaying } from '../../support/monitor-page';

test.describe('guided run before Start', () => {
  test('shows the idle page with step 1 current, the plan and empty readings in words', async ({ page }) => {
    await MockBackend.attach(page);
    const guided = guidedPage(page);

    await openGuidedRun(page);

    await expect(guided.phaseLine('Step 1 of 4, get comfy')).toBeVisible();
    await expectCurrentStep(page, 'Get comfy');
    await expect(guided.step('Warm-up')).toContainText('60 s');
    await expect(guided.step('Counted')).toContainText('90 s');
    await expect(guided.headline('Two and a half minutes, mostly doing nothing.')).toBeVisible();
    await expect(guided.panel.getByText("Camera's off. Press Start and your face shows up here.")).toBeVisible();
    await expect(guided.panel.getByText('No reading yet', { exact: true })).toBeVisible();
    await expect(guided.panel.getByText('Beat to beat variation', { exact: true })).toBeVisible();
    await expect(guided.panel.getByText('Overall rhythm variation', { exact: true })).toBeVisible();
    await expect(guided.notEnoughBeats).toHaveCount(2);
    await expect(guided.variationLater).toBeVisible();
    await expect(guided.disclaimer).toBeVisible();
    await expect(guided.start).toBeVisible();
    await expect(guided.stop).toHaveCount(0);
  });

  test('has the chime toggle on by default and turns it off and on with aria-pressed', async ({ page }) => {
    await MockBackend.attach(page);
    const guided = guidedPage(page);

    await openGuidedRun(page);

    await expect(guided.chime).toHaveAttribute('aria-pressed', 'true');
    await expect(guided.chime).toHaveAccessibleName('Chime at start and end: on');
    await guided.chime.click();
    await expect(guided.chime).toHaveAttribute('aria-pressed', 'false');
    await expect(guided.chime).toHaveAccessibleName('Chime at start and end: off');
    await guided.chime.click();
    await expect(guided.chime).toHaveAttribute('aria-pressed', 'true');
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
    await expect.poll(() => videoIsPlaying(guided.panel.getByLabel('Camera preview'))).toBe(true);
    await expect(guided.stop).toBeVisible();
  });
});
