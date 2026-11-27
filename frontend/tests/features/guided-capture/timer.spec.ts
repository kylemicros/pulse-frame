import { expect, test, type Locator } from '@playwright/test';
import { advanceRun, advanceRunUntil, guidedPage, startRun, timerSeconds } from '../../support/guided-page';
import { MockBackend } from '../../support/mock-backend';

type TimerParts = {
  numberPx: number;
  unitPx: number;
  numberColour: string;
  unitColour: string;
  gapPx: number;
  unitOwnElement: boolean;
};

const UNIT_SHARE_MAX = 0.7;
const SPACE_SHARE_MAX = 0.65;

function timerParts(timer: Locator): Promise<TimerParts> {
  return timer.evaluate((element) => {
    const texts: Text[] = [];
    const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT);
    for (let node = walker.nextNode(); node !== null; node = walker.nextNode()) {
      texts.push(node as Text);
    }
    const digits = texts.find((node) => /\d/.test(node.data));
    const unit = texts.findLast((node) => /s\s*$/.test(node.data));
    if (digits === undefined || unit === undefined) {
      return { numberPx: 0, unitPx: 0, numberColour: '', unitColour: '', gapPx: -1, unitOwnElement: false };
    }
    const digitMatch = /\d+/.exec(digits.data);
    const digitStart = digitMatch?.index ?? 0;
    const digitRange = document.createRange();
    digitRange.setStart(digits, digitStart);
    digitRange.setEnd(digits, digitStart + (digitMatch?.[0].length ?? 0));
    const unitRange = document.createRange();
    const unitAt = unit.data.lastIndexOf('s');
    unitRange.setStart(unit, unitAt);
    unitRange.setEnd(unit, unitAt + 1);
    const numberStyle = getComputedStyle(digits.parentElement ?? element);
    const unitStyle = getComputedStyle(unit.parentElement ?? element);
    return {
      numberPx: Number.parseFloat(numberStyle.fontSize),
      unitPx: Number.parseFloat(unitStyle.fontSize),
      numberColour: numberStyle.color,
      unitColour: unitStyle.color,
      gapPx: unitRange.getBoundingClientRect().left - digitRange.getBoundingClientRect().right,
      unitOwnElement: unit !== digits,
    };
  });
}

const STAGES = ['warm-up', 'counting'] as const;

test.describe('the countdown timer', () => {
  for (const stage of STAGES) {
    test(`reads as the number, one normal space and a smaller unit in the number's colour in the ${stage}`, async ({
      page,
    }) => {
      const backend = await MockBackend.attach(page);
      const guided = guidedPage(page);
      await startRun(page, backend);
      const timer = stage === 'warm-up' ? guided.warmUpTimer : guided.countedTimer;
      if (stage === 'counting') {
        await advanceRunUntil(page, backend, guided.countedTimer);
      }
      await advanceRun(page, backend, 2000, 1000);
      await expect(timer).toBeVisible();

      const seconds = await timerSeconds(timer);
      const parts = await timerParts(timer);

      expect(seconds).toBeGreaterThan(0);
      expect(parts.unitOwnElement, 'the unit is set apart from the number').toBe(true);
      expect(parts.unitPx, 'the unit size against the number size').toBeLessThanOrEqual(parts.numberPx * UNIT_SHARE_MAX);
      expect(parts.unitColour, 'the unit takes the colour of the number').toBe(parts.numberColour);
      expect(parts.gapPx, 'a space between the number and the unit').toBeGreaterThan(0);
      expect(parts.gapPx, 'at most one normal space between the number and the unit').toBeLessThanOrEqual(
        parts.numberPx * SPACE_SHARE_MAX,
      );
    });
  }
});
