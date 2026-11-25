import { expect, test, type Page } from '@playwright/test';
import { advanceRun, expectQuietRef, guidedPage, pushAndConfirm, startRun } from '../../support/guided-page';
import { hrv, MockBackend, type Hrv } from '../../support/mock-backend';
import { pageNow, settleRendering, waitForMoreFrames } from '../../support/page-helpers';
import { firstMessageAfter, socketRecords } from '../../support/socket-recorder';

const BAD_REPLY_WORDS =
  "The pulse reader sent something this page can't read, so it was ignored. The numbers may stall.";

const LIVE_READING = { bpm: 72.4, quality_db: 9.1, state: 'ok' } as const;

const VALID_MESSAGES: Array<{ name: string; fields: Hrv }> = [
  { name: 'with every value still null', fields: hrv() },
  {
    name: 'with both variation values, a minute heart rate and a range',
    fields: hrv({ rmssd_ms: 41.2, sdnn_ms: 46.5, minute_bpm: 91.3, minute_count: 72, bpm_low: 89.6, bpm_high: 93.1 }),
  },
  {
    name: 'with a range whose two ends are equal',
    fields: hrv({ minute_bpm: 68, minute_count: 72, bpm_low: 68, bpm_high: 68 }),
  },
  { name: 'saying the signal is too weak', fields: hrv({ no_reading: 'SIGNAL_TOO_WEAK', minute_count: 0 }) },
  {
    name: 'saying the face kept leaving the view',
    fields: hrv({ no_reading: 'READING_FLOOR_NOT_CLEARED', why: 'face_left_view', minute_count: 12 }),
  },
  {
    name: 'saying the pulse was faint with a share of exactly 0',
    fields: hrv({ no_reading: 'READING_FLOOR_NOT_CLEARED', why: 'faint_pulse', clear_percent: 0 }),
  },
];

const BASE = { type: 'hrv', t: 4000, ...hrv() };
const READING = { ...BASE, minute_bpm: 68.4, minute_count: 72 };
const RANGED = { ...READING, bpm_low: 66.6, bpm_high: 69.2 };
const FAINT = { ...BASE, no_reading: 'READING_FLOOR_NOT_CLEARED', why: 'faint_pulse', clear_percent: 18.4 };

function withRaw(fields: Record<string, unknown>, key: string, raw: string): string {
  return JSON.stringify({ ...fields, [key]: 'RAW_VALUE' }).replace('"RAW_VALUE"', raw);
}

function without(fields: Record<string, unknown>, key: string): string {
  const copy = { ...fields };
  Reflect.deleteProperty(copy, key);
  return JSON.stringify(copy);
}

const INVALID_MESSAGES: Array<{ name: string; text: string }> = [
  { name: 'no capture time', text: without(BASE, 't') },
  { name: 'a capture time given as text', text: JSON.stringify({ ...BASE, t: '4000' }) },
  { name: 'a beat to beat value given as text', text: JSON.stringify({ ...BASE, rmssd_ms: '41' }) },
  { name: 'an overall rhythm value given as true', text: JSON.stringify({ ...BASE, sdnn_ms: true }) },
  { name: 'a minute heart rate that overflows to infinity', text: withRaw(BASE, 'minute_bpm', '1e999') },
  { name: 'a beat to beat value that overflows to minus infinity', text: withRaw(BASE, 'rmssd_ms', '-1e999') },
  { name: 'a minute count that is not a whole number', text: JSON.stringify({ ...BASE, minute_count: 61.5 }) },
  { name: 'a minute count of null', text: JSON.stringify({ ...BASE, minute_count: null }) },
  { name: 'a range end given as text', text: JSON.stringify({ ...BASE, bpm_low: '66' }) },
  { name: 'a low range end without a high end', text: JSON.stringify({ ...RANGED, bpm_high: null }) },
  { name: 'a high range end without a low end', text: JSON.stringify({ ...RANGED, bpm_low: null }) },
  { name: 'a low range end above the high end', text: JSON.stringify({ ...RANGED, bpm_low: 69.3 }) },
  { name: 'a minute heart rate below the low range end', text: JSON.stringify({ ...RANGED, minute_bpm: 66.5 }) },
  { name: 'a minute heart rate above the high range end', text: JSON.stringify({ ...RANGED, minute_bpm: 69.3 }) },
  { name: 'a high range end that overflows to infinity', text: withRaw(RANGED, 'bpm_high', '1e999') },
  { name: 'no low range end field at all', text: without(READING, 'bpm_low') },
  {
    name: 'a range with no minute heart rate',
    text: JSON.stringify({ ...RANGED, minute_bpm: null }),
  },
  {
    name: 'a range on a too weak code',
    text: JSON.stringify({ ...RANGED, minute_bpm: null, no_reading: 'SIGNAL_TOO_WEAK' }),
  },
  {
    name: 'a range on a reading floor code',
    text: JSON.stringify({ ...FAINT, minute_count: 9, bpm_low: 66.6, bpm_high: 69.2 }),
  },
  { name: 'an unknown no reading code', text: JSON.stringify({ ...BASE, no_reading: 'SIGNAL_GONE' }) },
  { name: 'a no reading code in the wrong case', text: JSON.stringify({ ...BASE, no_reading: 'signal_too_weak' }) },
  {
    name: 'an unknown why code',
    text: JSON.stringify({ ...BASE, no_reading: 'READING_FLOOR_NOT_CLEARED', why: 'too_dark' }),
  },
  {
    name: 'a why code in the wrong case',
    text: JSON.stringify({ ...BASE, no_reading: 'READING_FLOOR_NOT_CLEARED', why: 'FACE_LEFT_VIEW' }),
  },
  { name: 'a faint pulse without its clear share', text: JSON.stringify({ ...FAINT, clear_percent: null }) },
  { name: 'a clear share given as text', text: JSON.stringify({ ...FAINT, clear_percent: '18' }) },
  { name: 'a clear share that overflows to infinity', text: withRaw(FAINT, 'clear_percent', '1e999') },
  { name: 'no why field at all', text: without(BASE, 'why') },
  {
    name: 'a reading floor code without a why',
    text: JSON.stringify({ ...BASE, no_reading: 'READING_FLOOR_NOT_CLEARED', why: null, clear_percent: 18.4 }),
  },
  {
    name: 'a too weak code that carries a why',
    text: JSON.stringify({ ...BASE, no_reading: 'SIGNAL_TOO_WEAK', why: 'face_left_view' }),
  },
  {
    name: 'a minute heart rate and a no reading code together',
    text: JSON.stringify({ ...BASE, minute_bpm: 68.2, minute_count: 70, no_reading: 'SIGNAL_TOO_WEAK' }),
  },
  { name: 'a negative minute count', text: JSON.stringify({ ...BASE, minute_count: -1 }) },
  { name: 'a clear share with no no reading code', text: JSON.stringify({ ...BASE, clear_percent: 12.2 }) },
  {
    name: 'a clear share on a face left view reason',
    text: JSON.stringify({ ...BASE, no_reading: 'READING_FLOOR_NOT_CLEARED', why: 'face_left_view', clear_percent: 72.4 }),
  },
  {
    name: 'a clear share on a too weak reason',
    text: JSON.stringify({ ...BASE, no_reading: 'SIGNAL_TOO_WEAK', clear_percent: 3.1 }),
  },
  {
    name: 'a minute heart rate and a reading floor code together',
    text: JSON.stringify({ ...FAINT, minute_bpm: 68.2, minute_count: 70 }),
  },
];

async function expectAccepted(page: Page, backend: MockBackend, fields: Hrv): Promise<void> {
  const guided = guidedPage(page);
  const since = await pageNow(page);
  const text = JSON.stringify({ type: 'hrv', t: Math.floor(since), ...fields });
  backend.sendLastBeforeHold(text);
  await expect
    .poll(async () => firstMessageAfter(await socketRecords(page), since, (message) => JSON.stringify(message) === text))
    .not.toBeNull();
  await settleRendering(page);
  await page.clock.runFor(500);
  await settleRendering(page);

  await expect(guided.main.getByText(BAD_REPLY_WORDS)).toHaveCount(0);
  await expect(guided.main.getByText('Ref: BAD_REPLY', { exact: true })).toHaveCount(0);
  backend.releaseReplies();
  await waitForMoreFrames(backend, 2);
}

test.describe('pulse reader hrv message', () => {
  for (const { name, fields } of VALID_MESSAGES) {
    test(`accepts an hrv message ${name} without calling it unreadable`, async ({ page }) => {
      await page.clock.install();
      const backend = await MockBackend.attach(page);
      const guided = guidedPage(page);
      await startRun(page, backend);

      await expectAccepted(page, backend, fields);

      await expect(guided.stop).toBeVisible();
    });
  }

  test('never shows the minute heart rate of an hrv message as the live heart rate', async ({ page }) => {
    await page.clock.install();
    const backend = await MockBackend.attach(page);
    const guided = guidedPage(page);
    await startRun(page, backend);
    await pushAndConfirm(page, backend, LIVE_READING);
    await expect(guided.liveReadings.getByText(/^72(\.4)?$/)).toBeVisible();

    await expectAccepted(page, backend, hrv({ minute_bpm: 91.3, minute_count: 72 }));
    await advanceRun(page, backend, 3000, 500);

    await expect(guided.liveReadings.getByText(/^72(\.4)?$/)).toBeVisible();
    await expect(guided.main).not.toContainText(/\b91(\.3)?\b/);
  });

  for (const { name, text } of INVALID_MESSAGES) {
    test(`shows BAD_REPLY in plain words for an hrv message with ${name}`, async ({ page }) => {
      await page.clock.install();
      const backend = await MockBackend.attach(page);
      const guided = guidedPage(page);
      await startRun(page, backend);
      await expectAccepted(page, backend, hrv());

      backend.sendUnreadableNext(text, { holdAfter: true });

      await expectQuietRef(guided.main, BAD_REPLY_WORDS, 'BAD_REPLY');
      await expect(guided.stop).toBeVisible();
      backend.releaseReplies();
      await waitForMoreFrames(backend, 3);
      await expect(guided.stop).toBeVisible();
    });
  }
});
