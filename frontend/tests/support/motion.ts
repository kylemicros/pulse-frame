import { expect, type Page } from '@playwright/test';

export type MotionTag = 'panel' | 'banner' | 'strip' | 'camera' | 'result' | 'lockWords' | 'settings' | 'scrim' | 'other';

export type Motion = {
  tag: MotionTag;
  kind: 'transition' | 'animation' | 'script' | 'computed';
  name: string;
  properties: string[];
  durationMs: number;
  iterations: number;
  text: string;
  midOpacity: number;
  endOpacity: number;
  midTransform: string;
  midTranslate: string;
  midScale: string;
  midRotate: string;
  lockHidden: boolean;
};

type MotionWindow = Window & { motionRecord: { seen: Motion[]; sweep: () => void; clear: () => void } };

export const PHASE_FADE_MS = 180;
export const QUICK_FADE_MS = 120;
export const SHEET_SLIDE_MS = 180;

export async function recordMotion(page: Page): Promise<void> {
  await page.addInitScript(() => {
    const seen: Motion[] = [];
    const known = new WeakSet<Animation>();
    const liveNames = new WeakMap<Element, Set<string>>();
    const marks = { panel: '[data-testid="run-panel"]', video: 'video[aria-label^="Camera preview"]', lock: 'Stays on this computer' };
    const lockHidden = (): boolean => {
      const lock = Array.from(document.querySelectorAll('button')).find(
        (button) => button.getAttribute('aria-label') === marks.lock,
      );
      return (
        lock === undefined ||
        lock.closest('[inert], [aria-hidden="true"]') !== null ||
        lock.getClientRects().length === 0 ||
        getComputedStyle(lock).visibility === 'hidden'
      );
    };
    const tagOf = (target: Element): MotionTag => {
      const panel = document.querySelector(marks.panel);
      const video = document.querySelector(marks.video);
      const cameraBox = video?.parentElement ?? null;
      const card =
        Array.from(document.querySelectorAll('main [aria-labelledby], main [aria-label]')).find((element) => {
          const label = element.getAttribute('aria-label');
          if (label !== null) {
            return label.trim() === 'Result';
          }
          const id = element.getAttribute('aria-labelledby') ?? '';
          return document.getElementById(id)?.textContent?.trim() === 'Result';
        }) ?? null;
      const holdsPanel = panel !== null && target.contains(panel) && target !== panel;
      if (target.closest('[role="dialog"]') !== null) {
        return 'settings';
      }
      if (target.closest('header') !== null) {
        return 'banner';
      }
      if (panel !== null && panel.contains(target)) {
        return 'panel';
      }
      if ((target.textContent ?? '').trim() === marks.lock && target.querySelector('button') === null) {
        return 'lockWords';
      }
      if (card !== null && !holdsPanel && (card.contains(target) || target.contains(card))) {
        return 'result';
      }
      if (cameraBox !== null && !holdsPanel && (cameraBox.contains(target) || target.contains(cameraBox))) {
        return 'camera';
      }
      const box = target.getBoundingClientRect();
      const style = getComputedStyle(target);
      if (target.getAttribute('aria-hidden') === 'true' && box.height > 0 && box.height <= 8 && target.closest('main') !== null) {
        return 'strip';
      }
      if (style.position === 'fixed' && (target.textContent ?? '').trim() === '' && box.width >= innerWidth && box.height >= innerHeight) {
        return 'scrim';
      }
      return 'other';
    };
    const noteLive = (target: Element, pseudo: string | null, name: string) => {
      const names = liveNames.get(target) ?? new Set<string>();
      names.add(`${pseudo ?? ''}|${name}`);
      liveNames.set(target, names);
    };
    const sample = (animation: Animation): Motion | null => {
      const effect = animation.effect;
      if (!(effect instanceof KeyframeEffect) || effect.target === null) {
        return null;
      }
      const target = effect.target;
      const pseudo = effect.pseudoElement;
      const timing = effect.getComputedTiming();
      const durationMs = typeof timing.duration === 'number' ? timing.duration : Number.NaN;
      const delay = effect.getTiming().delay ?? 0;
      const properties = Array.from(
        new Set(
          effect
            .getKeyframes()
            .flatMap((frame) => Object.keys(frame))
            .filter((key) => !['offset', 'computedOffset', 'easing', 'composite'].includes(key)),
        ),
      );
      const kind = animation instanceof CSSTransition ? 'transition' : animation instanceof CSSAnimation ? 'animation' : 'script';
      const name =
        animation instanceof CSSTransition
          ? animation.transitionProperty
          : animation instanceof CSSAnimation
            ? animation.animationName
            : animation.id;
      noteLive(target, pseudo, name);
      const before = animation.currentTime;
      const read = (at: number) => {
        animation.currentTime = at;
        const style = getComputedStyle(target, pseudo);
        return {
          opacity: Number.parseFloat(style.opacity),
          transform: style.transform,
          translate: style.translate,
          scale: style.scale,
          rotate: style.rotate,
        };
      };
      const mid = read(delay + durationMs / 2);
      const end = read(Math.max(delay + durationMs - 1, 0));
      animation.currentTime = before;
      return {
        tag: tagOf(target),
        kind,
        name,
        properties: kind === 'transition' ? [name] : properties,
        durationMs,
        iterations: Number(timing.iterations),
        text: (target.textContent ?? '').replaceAll(/\s+/g, ' ').trim().slice(0, 400),
        midOpacity: mid.opacity,
        endOpacity: end.opacity,
        midTransform: mid.transform,
        midTranslate: mid.translate,
        midScale: mid.scale,
        midRotate: mid.rotate,
        lockHidden: lockHidden(),
      };
    };
    const sweep = () => {
      for (const animation of document.getAnimations()) {
        if (known.has(animation)) {
          continue;
        }
        known.add(animation);
        const motion = sample(animation);
        if (motion !== null) {
          seen.push(motion);
        }
      }
    };
    const css = {
      listItem(list: string, index: number): string {
        const items = list.split(',').map((item) => item.trim());
        return items[index % items.length] ?? '';
      },
      toMs(text: string): number {
        return text.endsWith('ms') ? Number.parseFloat(text) : Number.parseFloat(text) * 1000;
      },
      keyframeProperties(name: string): string[] {
        const found = new Set<string>();
        for (const sheet of Array.from(document.styleSheets)) {
          for (const rule of Array.from(sheet.cssRules)) {
            if (rule instanceof CSSKeyframesRule && rule.name === name) {
              for (const frame of Array.from(rule.cssRules)) {
                if (frame instanceof CSSKeyframeRule) {
                  for (const property of Array.from(frame.style)) {
                    found.add(property);
                  }
                }
              }
            }
          }
        }
        return [...found];
      },
    };
    const recordEnded = (event: AnimationEvent | TransitionEvent) => {
      const target = event.target;
      if (!(target instanceof Element)) {
        return;
      }
      const isAnimation = event instanceof AnimationEvent;
      const name = isAnimation ? event.animationName : event.propertyName;
      const pseudo = event.pseudoElement === '' ? null : event.pseudoElement;
      if (liveNames.get(target)?.has(`${pseudo ?? ''}|${name}`) === true) {
        return;
      }
      noteLive(target, pseudo, name);
      const style = getComputedStyle(target, pseudo);
      const names = (isAnimation ? style.animationName : style.transitionProperty).split(',').map((item) => item.trim());
      const index = Math.max(names.indexOf(name), isAnimation ? 0 : names.indexOf('all'), 0);
      const properties = isAnimation ? css.keyframeProperties(name) : [name];
      const endOpacity = Number.parseFloat(style.opacity);
      const count = isAnimation ? css.listItem(style.animationIterationCount, index) : '1';
      seen.push({
        tag: tagOf(target),
        kind: 'computed',
        name,
        properties,
        durationMs: css.toMs(css.listItem(isAnimation ? style.animationDuration : style.transitionDuration, index)),
        iterations: count === 'infinite' ? Number.POSITIVE_INFINITY : Number.parseFloat(count),
        text: (target.textContent ?? '').replaceAll(/\s+/g, ' ').trim().slice(0, 400),
        midOpacity: properties.includes('opacity') ? 0.5 : endOpacity,
        endOpacity,
        midTransform: 'none',
        midTranslate: 'none',
        midScale: 'none',
        midRotate: 'none',
        lockHidden: lockHidden(),
      });
    };
    const onMotionEvent = (event: AnimationEvent | TransitionEvent) => {
      sweep();
      recordEnded(event);
    };
    const clear = () => {
      sweep();
      seen.splice(0);
    };
    Object.defineProperty(globalThis, 'motionRecord', { value: { seen, sweep, clear } });
    document.addEventListener('animationstart', onMotionEvent, true);
    document.addEventListener('transitionrun', onMotionEvent, true);
  });
}

export function clearMotion(page: Page): Promise<void> {
  return page.evaluate(() => (globalThis as unknown as MotionWindow).motionRecord.clear());
}

export function motionSeen(page: Page): Promise<Motion[]> {
  return page.evaluate(() => {
    const record = (globalThis as unknown as MotionWindow).motionRecord;
    record.sweep();
    return [...record.seen];
  });
}

export function animatesOpacity(motion: Motion): boolean {
  return motion.properties.includes('opacity');
}

export function computedMovesMore(motion: Motion): boolean {
  return motion.kind === 'computed' && motion.properties.some((property) => property !== 'opacity');
}

export function isFade(motion: Motion): boolean {
  const opacityOnly = motion.kind !== 'computed' || (motion.properties.length === 1 && motion.properties[0] === 'opacity');
  return opacityOnly && animatesOpacity(motion) && motion.midOpacity > 0.02 && motion.midOpacity < 0.98;
}

function matrixParts(transform: string): number[] | null {
  const match = /^matrix(3d)?\(([^)]*)\)$/.exec(transform.trim());
  return match === null ? null : match[2].split(',').map((part) => Number.parseFloat(part));
}

export function scalesOrTurns(motion: Motion): boolean {
  const parts = matrixParts(motion.midTransform);
  const matrixScales =
    parts !== null &&
    (parts.length === 6
      ? Math.abs(parts[0] - 1) > 0.001 || Math.abs(parts[1]) > 0.001 || Math.abs(parts[2]) > 0.001 || Math.abs(parts[3] - 1) > 0.001
      : Math.abs(parts[0] - 1) > 0.001 || Math.abs(parts[5] - 1) > 0.001 || Math.abs(parts[10] - 1) > 0.001);
  const scaleSet = !['none', '1', '1 1', '1 1 1'].includes(motion.midScale.trim());
  const rotateSet = !['none', '0deg'].includes(motion.midRotate.trim());
  return (
    matrixScales ||
    scaleSet ||
    rotateSet ||
    computedMovesMore(motion) ||
    motion.properties.some((property) => ['scale', 'rotate', 'zoom'].includes(property))
  );
}

export function shiftY(motion: Motion): number {
  const parts = matrixParts(motion.midTransform);
  const fromMatrix = parts === null ? 0 : parts.length === 6 ? parts[5] : parts[13];
  const translateParts = motion.midTranslate.trim() === 'none' ? [] : motion.midTranslate.trim().split(/\s+/);
  const fromTranslate = translateParts.length > 1 ? Number.parseFloat(translateParts[1]) : 0;
  return fromMatrix + fromTranslate;
}

export function shiftX(motion: Motion): number {
  const parts = matrixParts(motion.midTransform);
  const fromMatrix = parts === null ? 0 : parts.length === 6 ? parts[4] : parts[12];
  const translateParts = motion.midTranslate.trim() === 'none' ? [] : motion.midTranslate.trim().split(/\s+/);
  const fromTranslate = translateParts.length > 0 ? Number.parseFloat(translateParts[0]) : 0;
  return fromMatrix + fromTranslate;
}

export function slides(motion: Motion): boolean {
  return computedMovesMore(motion) || Math.abs(shiftX(motion)) > 0.5 || Math.abs(shiftY(motion)) > 0.5;
}

export async function expectFade(page: Page, tag: MotionTag, durationMs: number, holding: string | null = null): Promise<Motion[]> {
  const picked = (seen: Motion[]) =>
    seen.filter((motion) => motion.tag === tag && isFade(motion) && (holding === null || motion.text.includes(holding)));
  await expect
    .poll(async () => picked(await motionSeen(page)).length, {
      message: `an opacity fade on the ${tag}${holding === null ? '' : ` holding "${holding}"`}`,
    })
    .toBeGreaterThan(0);
  const seen = await motionSeen(page);
  const fades = picked(seen);
  expect(
    seen.filter((motion) => motion.tag === tag && computedMovesMore(motion) && (holding === null || motion.text.includes(holding))),
    `ended ${tag} motion that changes more than opacity`,
  ).toEqual([]);
  for (const fade of fades) {
    expect(fade.durationMs, `the ${tag} fade on "${fade.text.slice(0, 60)}" lasts`).toBe(durationMs);
    expect(fade.iterations, `the ${tag} fade runs once`).toBe(1);
    expect(scalesOrTurns(fade), `the ${tag} fade scales or turns: ${JSON.stringify(fade)}`).toBe(false);
  }
  return fades;
}

export function movingParts(seen: Motion[], tags: readonly MotionTag[]): Motion[] {
  return seen.filter((motion) => tags.includes(motion.tag) && motion.durationMs > 0 && (animatesOpacity(motion) || slides(motion) || scalesOrTurns(motion)));
}
