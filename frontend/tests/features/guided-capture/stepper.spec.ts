import { expect, test, type Page } from '@playwright/test';
import {
  advanceRun,
  advanceRunUntil,
  expectCurrentStep,
  expectStoppedStep,
  guidedPage,
  openGuidedRun,
  pushAndConfirm,
  startCheck,
  startRun,
  STEP_NAMES,
  type StepName,
} from '../../support/guided-page';
import { FAR_FACE } from '../../support/app-shell';
import { headerLogo } from '../../support/brand';
import { MockBackend } from '../../support/mock-backend';
import { boxOf } from '../../support/page-helpers';
import { drawn, settingsPanel } from '../../support/settings';

const DROPPED = { code: 1006 };
const ROW_SLACK_PX = 8;
const ONE_ROW_HIGH_PX = 48;

type Middle = { name: string; middle: number };

function otherSteps(current: StepName): StepName[] {
  return STEP_NAMES.filter((name) => name !== current);
}

async function middlesOf(page: Page): Promise<Middle[]> {
  const guided = guidedPage(page);
  const settings = settingsPanel(page);
  const middles: Middle[] = [];
  for (const [name, locator] of [
    ['the name', headerLogo(page).wordmark],
    ['the stepper', guided.stepList],
    ['the gear', settings.gear],
    ['the main button', guided.start],
  ] as const) {
    const box = await boxOf(locator);
    middles.push({ name, middle: box.y + box.height / 2 });
  }
  return middles;
}

async function stepTops(page: Page): Promise<number[]> {
  const tops: number[] = [];
  for (const name of STEP_NAMES) {
    tops.push(Math.round((await boxOf(guidedPage(page).step(name))).y));
  }
  return tops;
}

test.describe('the header row on a desktop', () => {
  test.use({ viewport: { width: 1280, height: 800 } });

  test('lines up the name, the stepper, the Settings gear and the main button on one header row', async ({ page }) => {
    await MockBackend.attach(page);
    const guided = guidedPage(page);
    const banner = page.getByRole('banner');
    await openGuidedRun(page);

    await expect(banner.getByRole('list', { name: 'Capture steps' })).toBeVisible();
    await expect(banner.getByRole('button', { name: 'Settings', exact: true })).toBeVisible();
    await expect(banner.getByRole('button', { name: 'Start', exact: true })).toBeVisible();
    const middles = await middlesOf(page);
    const name = await boxOf(headerLogo(page).wordmark);
    const steps = await boxOf(guided.stepList);
    const gear = await boxOf(settingsPanel(page).gear);
    const button = await boxOf(guided.start);

    for (const { name: part, middle } of middles) {
      expect(Math.abs(middle - middles[0].middle), `${part} off the row of the name`).toBeLessThanOrEqual(ROW_SLACK_PX);
    }
    expect(steps.x, 'the stepper comes after the name').toBeGreaterThanOrEqual(name.x + name.width - 1);
    expect(gear.x, 'the gear comes after the stepper').toBeGreaterThanOrEqual(steps.x + steps.width - 1);
    expect(button.x, 'the main button comes after the gear').toBeGreaterThanOrEqual(gear.x + gear.width - 1);
  });

  test('draws the four steps in one row no taller than the header controls', async ({ page }) => {
    await MockBackend.attach(page);
    const guided = guidedPage(page);
    await openGuidedRun(page);

    const tops = await stepTops(page);
    const steps = await boxOf(guided.stepList);

    expect(Math.max(...tops) - Math.min(...tops), 'the steps sit on one row').toBeLessThanOrEqual(2);
    expect(steps.height, 'the stepper height').toBeLessThanOrEqual(ONE_ROW_HIGH_PX);
    for (const name of STEP_NAMES) {
      expect(await drawn(guided.stepName(name)), `${name} named on a desktop`).toBe(true);
    }
  });

  test('shows the step once: no step line and no step list in the page under the header', async ({ page }) => {
    await page.clock.install();
    const backend = await MockBackend.attach(page);
    const guided = guidedPage(page);
    await openGuidedRun(page);

    await expect(page.getByRole('list', { name: 'Capture steps' })).toHaveCount(1);
    await expect(guided.main.getByRole('list', { name: 'Capture steps' })).toHaveCount(0);
    await expect(guided.oldStepLine).toHaveCount(0);

    await startRun(page, backend);

    await expectCurrentStep(page, 'Warm-up');
    await expect(guided.oldStepLine).toHaveCount(0);
  });

  test('keeps the main button in the header row through the run and after Stop', async ({ page }) => {
    await page.clock.install();
    const backend = await MockBackend.attach(page);
    const guided = guidedPage(page);
    const banner = page.getByRole('banner');
    await startRun(page, backend);

    await expect(banner.getByRole('button', { name: 'Stop', exact: true })).toBeVisible();
    await expect(guided.main.getByRole('button', { name: 'Stop', exact: true })).toHaveCount(0);

    await guided.stop.click();

    await expect(banner.getByRole('button', { name: 'Start again', exact: true })).toBeVisible();
    await expect(guided.main.getByRole('button', { name: 'Start again', exact: true })).toHaveCount(0);
  });

  test('marks the current step Now with its number and ticks the done steps as the run moves on', async ({ page }) => {
    await page.clock.install();
    const backend = await MockBackend.attach(page);
    const guided = guidedPage(page);
    await startRun(page, backend);
    await pushAndConfirm(page, backend, { bpm: 68.2, quality_db: 9.4, state: 'ok' });

    await advanceRunUntil(page, backend, guided.countedTimer);

    await expectCurrentStep(page, 'Counted');
    await expect(guided.step('Counted')).toContainText('3');
    for (const name of ['Get comfy', 'Warm-up'] as const) {
      await expect(guided.step(name).locator('svg'), `${name} shows a tick`).toHaveCount(1);
      await expect(guided.step(name)).not.toContainText(name === 'Get comfy' ? '1' : '2');
    }
  });

  test('keeps the warm-up step marked Stopped after Stop, with no step marked Now, until the next Start', async ({
    page,
  }) => {
    await page.clock.install();
    const backend = await MockBackend.attach(page);
    const guided = guidedPage(page);
    await startRun(page, backend);
    await advanceRun(page, backend, 10000);

    await guided.stop.click();

    await expect(guided.startAgain).toBeVisible();
    await expectStoppedStep(page, 'Warm-up');
    await expect(guided.step('Warm-up').getByText('Stopped', { exact: true })).toBeVisible();

    await page.clock.runFor(30000);

    await expectStoppedStep(page, 'Warm-up');

    await guided.startAgain.click();

    await expectCurrentStep(page, 'Get comfy');
  });

  test('marks the first step Stopped, with no step current, when Stop is pressed during the setup check', async ({
    page,
  }) => {
    const backend = await MockBackend.attach(page);
    backend.setScene(FAR_FACE);
    const guided = guidedPage(page);
    await startCheck(page, backend);
    await expect(guided.stop).toBeVisible();
    await expect(guided.warmUpTimer).toHaveCount(0);

    await guided.stop.click();

    await expect(guided.start.or(guided.startAgain)).toBeVisible();
    await expectStoppedStep(page, 'Get comfy');
    await expect(guided.step('Get comfy').getByText('Stopped', { exact: true })).toBeVisible();
  });

  test('keeps the counted step marked Stopped when the link to the pulse reader drops while counting', async ({
    page,
  }) => {
    await page.clock.install();
    const backend = await MockBackend.attach(page);
    const guided = guidedPage(page);
    await startRun(page, backend);
    await advanceRunUntil(page, backend, guided.countedTimer);

    backend.refuseEveryConnection(DROPPED);
    backend.dropOpenConnections(DROPPED);

    await expect(guided.main.getByText('Ref: SOCKET_UNAVAILABLE', { exact: true })).toBeVisible();
    await expect(guided.startAgain).toBeVisible();
    await expectStoppedStep(page, 'Counted');
  });
});

test.describe('the header on a tablet', () => {
  test.use({ viewport: { width: 820, height: 1180 } });

  test('keeps the gear and the main button in the header with every step named on the row under them', async ({
    page,
  }) => {
    await MockBackend.attach(page);
    const guided = guidedPage(page);
    const banner = page.getByRole('banner');
    await openGuidedRun(page);

    await expect(banner.getByRole('button', { name: 'Start', exact: true })).toBeVisible();
    await expect(banner.getByRole('button', { name: 'Settings', exact: true })).toBeVisible();
    const name = await boxOf(headerLogo(page).wordmark);
    const steps = await boxOf(guided.stepList);
    const button = await boxOf(guided.start);
    const tops = await stepTops(page);

    expect(steps.y, 'the stepper sits under the name row').toBeGreaterThanOrEqual(name.y + name.height - 1);
    expect(steps.y, 'the stepper sits under the main button').toBeGreaterThanOrEqual(button.y + button.height - 1);
    expect(Math.max(...tops) - Math.min(...tops), 'the steps sit on one row').toBeLessThanOrEqual(2);
    for (const step of STEP_NAMES) {
      expect(await drawn(guided.stepName(step)), `${step} named on a tablet`).toBe(true);
    }
  });
});

test.describe('the compact stepper on a phone', () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test('names only the current step while all four stay listed, on one row inside the screen', async ({ page }) => {
    await page.clock.install();
    const backend = await MockBackend.attach(page);
    const guided = guidedPage(page);
    await openGuidedRun(page);

    await expectCurrentStep(page, 'Get comfy');
    expect(await drawn(guided.stepName('Get comfy')), 'the current step named').toBe(true);
    for (const name of otherSteps('Get comfy')) {
      expect(await drawn(guided.stepName(name)), `${name} named while not current`).toBe(false);
    }
    const tops = await stepTops(page);
    expect(Math.max(...tops) - Math.min(...tops), 'the steps sit on one row').toBeLessThanOrEqual(2);
    const steps = await boxOf(guided.stepList);
    expect(steps.x).toBeGreaterThanOrEqual(0);
    expect(steps.x + steps.width).toBeLessThanOrEqual(390);

    await startRun(page, backend);

    await expectCurrentStep(page, 'Warm-up');
    expect(await drawn(guided.stepName('Warm-up')), 'the current step named').toBe(true);
    for (const name of otherSteps('Warm-up')) {
      expect(await drawn(guided.stepName(name)), `${name} named while not current`).toBe(false);
    }
  });

  test('keeps the gear in the header and the main button out of it, in the bottom bar', async ({ page }) => {
    await MockBackend.attach(page);
    const guided = guidedPage(page);
    const banner = page.getByRole('banner');
    await openGuidedRun(page);

    await expect(banner.getByRole('button', { name: 'Settings', exact: true })).toBeVisible();
    await expect(banner.getByRole('list', { name: 'Capture steps' })).toBeVisible();
    await expect(banner.getByRole('button', { name: 'Start', exact: true })).toHaveCount(0);
    await expect(guided.start).toHaveCount(1);
    await expect(guided.start).toBeVisible();
  });

  test('names the stopped step with its Stopped mark after Stop', async ({ page }) => {
    await page.clock.install();
    const backend = await MockBackend.attach(page);
    const guided = guidedPage(page);
    await startRun(page, backend);
    await advanceRun(page, backend, 10000);

    await guided.stop.click();

    await expectStoppedStep(page, 'Warm-up');
    expect(await drawn(guided.stepName('Warm-up')), 'the stopped step named').toBe(true);
    expect(await drawn(guided.step('Warm-up').getByText('Stopped', { exact: true })), 'the Stopped word drawn').toBe(
      true,
    );
  });
});
