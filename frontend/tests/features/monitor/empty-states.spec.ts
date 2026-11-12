import { expect, test, type Locator } from '@playwright/test';
import { MockBackend, pulseSamples } from '../../support/mock-backend';
import {
  boxOf,
  holdCamera,
  longestPathCommands,
  monitorPage,
  releaseCamera,
  startMonitoring,
  videoIsPlaying,
} from '../../support/monitor-page';

async function expectCentredInside(inner: Locator, outer: Locator): Promise<void> {
  const box = await boxOf(inner);
  const area = await boxOf(outer);
  const centreX = box.x + box.width / 2;
  const centreY = box.y + box.height / 2;
  expect(centreX).toBeGreaterThan(area.x);
  expect(centreX).toBeLessThan(area.x + area.width);
  expect(centreY).toBeGreaterThan(area.y);
  expect(centreY).toBeLessThan(area.y + area.height);
}

async function shownText(locator: Locator): Promise<string> {
  await expect(locator).toBeVisible();
  const text = (await locator.innerText()).trim();
  expect(text.length).toBeGreaterThan(5);
  return text;
}

test.describe('empty states', () => {
  test('shows idle text over the empty pulse chart and different text while running until the trace draws', async ({
    page,
  }) => {
    const backend = await MockBackend.attach(page);
    const monitor = monitorPage(page);
    const emptyPulse = monitor.pulse.getByTestId('pulse-empty');

    await page.goto('/');
    const idleText = await shownText(emptyPulse);
    await expectCentredInside(emptyPulse, monitor.pulse);

    await monitor.start.click();
    await expect.poll(() => backend.frames.length).toBeGreaterThan(1);

    await expect(emptyPulse).not.toHaveText(idleText);
    await shownText(emptyPulse);
    await expectCentredInside(emptyPulse, monitor.pulse);

    backend.pushReading({ bpm: 72.4, quality_db: 6.5, state: 'ok' }, pulseSamples(300));

    await expect.poll(() => longestPathCommands(monitor.pulse)).toBeGreaterThan(50);
    await expect(emptyPulse).toBeHidden();
  });

  test('shows idle text in the video box before Start and starting text while the camera wakes', async ({ page }) => {
    await holdCamera(page);
    await MockBackend.attach(page);
    const monitor = monitorPage(page);
    const emptyVideo = page.getByTestId('video-empty');

    await page.goto('/');
    const idleText = await shownText(emptyVideo);
    await expectCentredInside(emptyVideo, monitor.video);

    await monitor.start.click();

    await expect(emptyVideo).not.toHaveText(idleText);
    await shownText(emptyVideo);
    await expectCentredInside(emptyVideo, monitor.video);

    await releaseCamera(page);

    await expect.poll(() => videoIsPlaying(monitor.video)).toBe(true);
    await expect(emptyVideo).toBeHidden();
  });

  test('says No value yet. for quality before Start', async ({ page }) => {
    await MockBackend.attach(page);
    const monitor = monitorPage(page);

    await page.goto('/');

    await expect(monitor.quality.getByText('No value yet.', { exact: true })).toBeVisible();
    await expect(monitor.quality).not.toContainText(/\d/);
  });

  test('shows the running text over the pulse chart again when the samples are cleared', async ({ page }) => {
    const backend = await MockBackend.attach(page);
    const monitor = monitorPage(page);
    const emptyPulse = monitor.pulse.getByTestId('pulse-empty');

    await startMonitoring(page, backend);
    backend.pushReading({ bpm: 72.4, quality_db: 6.5, state: 'ok' }, pulseSamples(300));
    await expect.poll(() => longestPathCommands(monitor.pulse)).toBeGreaterThan(50);
    await expect(emptyPulse).toBeHidden();

    backend.pushReading({ bpm: null, quality_db: null, state: 'acquiring' }, []);

    await expect.poll(() => longestPathCommands(monitor.pulse)).toBeLessThan(5);
    await shownText(emptyPulse);
  });
});
