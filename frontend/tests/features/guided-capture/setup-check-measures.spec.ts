import { expect, test } from '@playwright/test';
import {
  addSetupSample,
  advanceSetupCheck,
  faceBox,
  lightIn,
  newSetupCheck,
  restartSetupSpeed,
  SETUP_BACKLIGHT_SHARE,
  SETUP_BRIGHTNESS_MAX,
  SETUP_BRIGHTNESS_MIN,
  SETUP_MIN_FACE_SPAN_PX,
  SETUP_NEAR_WHITE,
  setupRows,
  type FaceBox,
  type FrameLight,
  type SetupCheck,
  type SetupSample,
} from '../../../src/features/guided-capture/lib/setup-check';
import { FRAME_SPACING_MS } from '../../support/guided-page';

const SIDE = 90;
const MIDDLE_THIRD: FaceBox = { left: 1 / 3, top: 1 / 3, right: 2 / 3, bottom: 2 / 3 };
const EVEN: FrameLight = { brightness: Math.round((SETUP_BRIGHTNESS_MIN + SETUP_BRIGHTNESS_MAX) / 2), backlitShare: 0 };
const SETTLED_MS = 2500;
const SHARE_STEP = 0.001;
const SPEED_GAP_MS = 1500;

function sample(change: Partial<SetupSample> = {}): SetupSample {
  return { face: true, spanPx: SETUP_MIN_FACE_SPAN_PX * 2, moving: false, light: EVEN, ...change };
}

function fed(each: SetupSample, untilMs = SETTLED_MS): SetupCheck {
  let check = newSetupCheck(0);
  for (let at = 0; at <= untilMs; at += FRAME_SPACING_MS) {
    check = addSetupSample(check, each, at);
  }
  return check;
}

function lastAt(untilMs = SETTLED_MS): number {
  return Math.floor(untilMs / FRAME_SPACING_MS) * FRAME_SPACING_MS;
}

function frame(face: number, around: number, box: FaceBox): Uint8ClampedArray {
  const pixels = new Uint8ClampedArray(SIDE * SIDE * 4);
  for (let y = 0; y < SIDE; y += 1) {
    for (let x = 0; x < SIDE; x += 1) {
      const inside =
        x >= Math.floor(box.left * SIDE) &&
        x < Math.ceil(box.right * SIDE) &&
        y >= Math.floor(box.top * SIDE) &&
        y < Math.ceil(box.bottom * SIDE);
      const level = inside ? face : around;
      pixels.set([level, level, level, 255], (y * SIDE + x) * 4);
    }
  }
  return pixels;
}

test.describe('setup check measures', () => {
  test('counts a face span at the threshold as close enough and one pixel under as too far', () => {
    const at = fed(sample({ spanPx: SETUP_MIN_FACE_SPAN_PX }));
    const under = fed(sample({ spanPx: SETUP_MIN_FACE_SPAN_PX - 1 }));

    expect(setupRows(at, lastAt()).distance).toBe(true);
    expect(at.shown).toBe('allGood');
    expect(setupRows(under, lastAt()).distance).toBe(false);
    expect(under.shown).toBe('far');
  });

  for (const { name, brightness, shown } of [
    { name: 'at the bottom of the band', brightness: SETUP_BRIGHTNESS_MIN, shown: 'allGood' },
    { name: 'at the top of the band', brightness: SETUP_BRIGHTNESS_MAX, shown: 'allGood' },
    { name: 'one step under the band', brightness: SETUP_BRIGHTNESS_MIN - 1, shown: 'dark' },
    { name: 'one step over the band', brightness: SETUP_BRIGHTNESS_MAX + 1, shown: 'bright' },
  ] as const) {
    test(`judges a face brightness ${name}`, () => {
      const check = fed(sample({ light: { brightness, backlitShare: 0 } }));

      expect(setupRows(check, lastAt()).light).toBe(shown === 'allGood');
      expect(check.shown).toBe(shown);
    });
  }

  test('says light behind you just over the backlight share and not just under it', () => {
    const over = fed(sample({ light: { ...EVEN, backlitShare: SETUP_BACKLIGHT_SHARE + SHARE_STEP } }));
    const under = fed(sample({ light: { ...EVEN, backlitShare: SETUP_BACKLIGHT_SHARE - SHARE_STEP } }));

    expect(over.shown).toBe('behind');
    expect(setupRows(over, lastAt()).light).toBe(false);
    expect(under.shown).toBe('allGood');
    expect(setupRows(under, lastAt()).light).toBe(true);
  });

  test('does not say light behind you at exactly the backlight share', () => {
    const at = fed(sample({ light: { ...EVEN, backlitShare: SETUP_BACKLIGHT_SHARE } }));

    expect(at.shown).toBe('allGood');
    expect(setupRows(at, lastAt()).light).toBe(true);
  });

  test('forgets the camera speed when the link stops being live, so the camera is never blamed for it', () => {
    const steady = fed(sample({ moving: true }));
    const quietUntil = lastAt() + SPEED_GAP_MS;

    const blamed = advanceSetupCheck(steady, quietUntil);
    const restarted = advanceSetupCheck(restartSetupSpeed(steady), quietUntil);

    expect(steady.shown).toBe('moving');
    expect(blamed.shown, 'without the restart a quiet link reads as a slow camera').toBe('slow');
    expect(setupRows(blamed, quietUntil).speed).toBe(false);
    expect(restarted.shown).toBe('moving');
    expect(restarted.shown).not.toBe('slow');
    expect(setupRows(restarted, quietUntil)).toEqual({ distance: true, light: true, stillness: false, speed: false });
    expect(restarted.goodSince).toBeNull();
  });

  test('puts light behind you before too dark when a backlit face is also dark', () => {
    const check = fed(sample({ light: { brightness: SETUP_BRIGHTNESS_MIN - 1, backlitShare: 1 } }));

    expect(check.shown).toBe('behind');
  });

  test('measures the face brightness and the near white ring share from the pixels', () => {
    const lit = lightIn(frame(SETUP_BRIGHTNESS_MIN, 128, MIDDLE_THIRD), SIDE, SIDE, MIDDLE_THIRD);
    const backlit = lightIn(frame(128, SETUP_NEAR_WHITE + 1, MIDDLE_THIRD), SIDE, SIDE, MIDDLE_THIRD);
    const atWhite = lightIn(frame(128, SETUP_NEAR_WHITE, MIDDLE_THIRD), SIDE, SIDE, MIDDLE_THIRD);

    expect(lit?.brightness).toBeCloseTo(SETUP_BRIGHTNESS_MIN, 3);
    expect(lit?.backlitShare).toBe(0);
    expect(backlit?.backlitShare).toBe(1);
    expect(atWhite?.backlitShare).toBe(0);
  });

  test('gives a share of 0 when the face box leaves no ring around it', () => {
    const whole: FaceBox = { left: 0, top: 0, right: 1, bottom: 1 };

    const light = lightIn(frame(128, 128, whole), SIDE, SIDE, whole);

    expect(light).toEqual({ brightness: expect.closeTo(128, 3), backlitShare: 0 });
  });

  test('measures no light when the face box holds no pixels', () => {
    const flat: FaceBox = { left: 0.5, top: 0.4, right: 0.5, bottom: 0.6 };

    expect(lightIn(frame(128, 128, flat), SIDE, SIDE, flat)).toBeNull();
  });

  test('clamps outline points outside the frame to its edges and finds no box without points', () => {
    expect(
      faceBox([
        [
          [-0.2, 0.1],
          [1.3, 0.5],
        ],
        null,
        [[0.5, 1.4]],
      ]),
    ).toEqual({ left: 0, top: 0.1, right: 1, bottom: 1 });
    expect(faceBox([null, null, null])).toBeNull();
  });

  test('counts Light as good when a face is found but its light cannot be measured', () => {
    const check = fed(sample({ light: null }));

    expect(setupRows(check, lastAt()).light).toBe(true);
    expect(check.shown).toBe('allGood');
    expect(check.goodSince).not.toBeNull();
  });

  test('clears a stale all good at once when the all good wait is not running', () => {
    const stale: SetupCheck = {
      startedAt: 0,
      sample: sample(),
      firstSampleAt: 1500,
      recent: [1500],
      shown: 'allGood',
      shownAt: 1800,
      goodSince: null,
    };

    const next = advanceSetupCheck(stale, 2100);

    expect(next.goodSince).toBeNull();
    expect(next.shown).toBeNull();
  });

  test('clears a stale prompt once its hold ends even when nothing else is wanted', () => {
    const stale: SetupCheck = {
      startedAt: 0,
      sample: sample(),
      firstSampleAt: 1500,
      recent: [1500],
      shown: 'moving',
      shownAt: 0,
      goodSince: null,
    };

    expect(advanceSetupCheck(stale, 1900).shown).toBe('moving');
    expect(advanceSetupCheck(stale, 2100).shown).toBeNull();
  });
});
