import { expect, type Locator, type Page } from '@playwright/test';
import type { MockBackend, PatchName } from './mock-backend';

type Box = { x: number; y: number; width: number; height: number };

type CameraSpy = { calls: number; streams: MediaStream[] };
type CameraWindow = Window & { cameraSpy: CameraSpy };

export function monitorPage(page: Page) {
  return {
    start: page.getByRole('button', { name: 'Start', exact: true }),
    stop: page.getByRole('button', { name: 'Stop', exact: true }),
    video: page.getByLabel('Camera preview'),
    overlay: page.getByRole('img', { name: 'Skin patch overlay' }),
    outlines: page.getByTestId(/^patch-outline-/),
    outline: (name: PatchName): Locator => page.getByTestId(`patch-outline-${name}`),
    overlayToggle: page.getByRole('button', { name: /overlay/i }),
    heartRate: page.getByRole('region', { name: 'Heart rate' }),
    bpmValue: page.getByTestId('bpm-value'),
    quality: page.getByRole('region', { name: 'Signal quality' }),
    pulse: page.getByRole('region', { name: 'Pulse waveform' }),
    glanceNotice: page.getByText(/(glanc|look)\w* away/i),
    alertWith: (code: string): Locator => page.getByRole('alert').filter({ hasText: code }),
    linkStatus: page
      .locator('header')
      .filter({ has: page.getByRole('heading', { name: 'pulse-frame', exact: true }) })
      .getByRole('status'),
  };
}

export async function startMonitoring(page: Page, backend: MockBackend): Promise<void> {
  await page.goto('/');
  await monitorPage(page).start.click();
  await expect.poll(() => backend.frames.length).toBeGreaterThan(1);
}

export async function waitForMoreFrames(backend: MockBackend, count: number): Promise<void> {
  const target = backend.frames.length + count;
  await expect.poll(() => backend.frames.length).toBeGreaterThanOrEqual(target);
}

export async function spyOnCamera(page: Page): Promise<void> {
  await page.addInitScript(() => {
    const spy = { calls: 0, streams: [] as MediaStream[] };
    Object.defineProperty(globalThis, 'cameraSpy', { value: spy });
    const devices = navigator.mediaDevices;
    const original = devices.getUserMedia.bind(devices);
    devices.getUserMedia = async (constraints?: MediaStreamConstraints) => {
      spy.calls += 1;
      const stream = await original(constraints);
      spy.streams.push(stream);
      return stream;
    };
  });
}

type CameraErrorName =
  | 'NotAllowedError'
  | 'NotFoundError'
  | 'NotReadableError'
  | 'AbortError'
  | 'OverconstrainedError'
  | 'TypeError'
  | 'InvalidStateError';

export async function refuseCamera(page: Page, errorName: CameraErrorName): Promise<void> {
  await page.addInitScript((name) => {
    const refusal = (): Error => {
      if (name === 'TypeError') {
        return new TypeError('Camera refused by the test');
      }
      if (name === 'OverconstrainedError' && typeof OverconstrainedError === 'function') {
        return new OverconstrainedError('width', 'Camera refused by the test');
      }
      return new DOMException('Camera refused by the test', name);
    };
    navigator.mediaDevices.getUserMedia = () => Promise.reject(refusal());
  }, errorName);
}

export async function removeCameraApi(page: Page, missing: 'mediaDevices' | 'getUserMedia'): Promise<void> {
  await page.addInitScript((part) => {
    if (part === 'mediaDevices') {
      Reflect.deleteProperty(Navigator.prototype, 'mediaDevices');
    } else {
      Reflect.deleteProperty(MediaDevices.prototype, 'getUserMedia');
    }
  }, missing);
}

type HeldCameraWindow = Window & { releaseCamera: () => void };

export async function holdCamera(page: Page): Promise<void> {
  await page.addInitScript(() => {
    let release: (() => void) | null = null;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    Object.defineProperty(globalThis, 'releaseCamera', { value: () => release?.() });
    const devices = navigator.mediaDevices;
    const original = devices.getUserMedia.bind(devices);
    devices.getUserMedia = async (constraints?: MediaStreamConstraints) => {
      await gate;
      return original(constraints);
    };
  });
}

export function releaseCamera(page: Page): Promise<void> {
  return page.evaluate(() => (globalThis as unknown as HeldCameraWindow).releaseCamera());
}

type RejectionWindow = Window & { unhandledRejections: string[] };

export async function recordUnhandledRejections(page: Page): Promise<void> {
  await page.addInitScript(() => {
    const reasons: string[] = [];
    Object.defineProperty(globalThis, 'unhandledRejections', { value: reasons });
    globalThis.addEventListener('unhandledrejection', (event) => {
      reasons.push(String(event.reason));
    });
  });
}

export function unhandledRejections(page: Page): Promise<string[]> {
  return page.evaluate(() => [...(globalThis as unknown as RejectionWindow).unhandledRejections]);
}

type EncodingFailure = 'yields no image' | 'throws';

export function failFrameEncoding(page: Page, failure: EncodingFailure): Promise<void> {
  return page.evaluate((how) => {
    HTMLCanvasElement.prototype.toBlob = function brokenToBlob(callback: BlobCallback) {
      if (how === 'throws') {
        throw new DOMException('The canvas refused to encode in the test', 'SecurityError');
      }
      globalThis.setTimeout(() => callback(null), 0);
    };
  }, failure);
}

export async function failPreviewAttach(page: Page): Promise<void> {
  await page.addInitScript(() => {
    const descriptor = Object.getOwnPropertyDescriptor(HTMLMediaElement.prototype, 'srcObject');
    if (descriptor?.get === undefined || descriptor.set === undefined) {
      throw new Error('HTMLMediaElement.srcObject is not an accessor in this browser');
    }
    const { get, set } = descriptor;
    Object.defineProperty(HTMLMediaElement.prototype, 'srcObject', {
      configurable: true,
      get(this: HTMLMediaElement) {
        return get.call(this);
      },
      set(this: HTMLMediaElement, value: MediaProvider | null) {
        if (value !== null) {
          throw new TypeError('The preview refused the camera stream in the test');
        }
        set.call(this, value);
      },
    });
  });
}

export const CODED_ALERT_TEXT = /\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b/;

export function ownTextLength(text: string, ...known: string[]): number {
  return known.reduce((rest, part) => rest.replace(part, ''), text).trim().length;
}

export function cameraCalls(page: Page): Promise<number> {
  return page.evaluate(() => (globalThis as unknown as CameraWindow).cameraSpy.calls);
}

export function cameraTrackStates(page: Page): Promise<string[]> {
  return page.evaluate(() =>
    (globalThis as unknown as CameraWindow).cameraSpy.streams.flatMap((stream) =>
      stream.getTracks().map((track) => track.readyState),
    ),
  );
}

export function videoIsPlaying(video: Locator): Promise<boolean> {
  return video.evaluate(
    (element) =>
      element instanceof HTMLVideoElement &&
      element.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA &&
      !element.paused &&
      element.currentTime > 0,
  );
}

export function longestPathCommands(region: Locator): Promise<number> {
  return region.evaluate((element) =>
    Math.max(
      0,
      ...Array.from(element.querySelectorAll('path')).map(
        (path) => (path.getAttribute('d') ?? '').match(/[LCQSTAHV]/gi)?.length ?? 0,
      ),
    ),
  );
}

export function collectPageErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  page.on('console', (message) => {
    if (message.type() === 'error') {
      errors.push(message.text());
    }
  });
  return errors;
}

export async function boxOf(locator: Locator): Promise<Box> {
  const box = await locator.boundingBox();
  expect(box).not.toBeNull();
  return box as Box;
}

type TextChange = { at: number; text: string };

type WatchWindow = Window & { textWatches: Record<string, TextChange[]> };

export async function watchText(locator: Locator, name: string): Promise<void> {
  await locator.evaluate((element, key) => {
    const host = globalThis as unknown as WatchWindow;
    host.textWatches ??= {};
    const changes: TextChange[] = [{ at: performance.now(), text: element.textContent ?? '' }];
    host.textWatches[key] = changes;
    new MutationObserver(() => {
      const text = element.textContent ?? '';
      if (changes.at(-1)?.text !== text) {
        changes.push({ at: performance.now(), text });
      }
    }).observe(element, { characterData: true, childList: true, subtree: true });
  }, name);
}

export function watchedText(page: Page, name: string): Promise<TextChange[]> {
  return page.evaluate((key) => (globalThis as unknown as WatchWindow).textWatches[key], name);
}

export function pageNow(page: Page): Promise<number> {
  return page.evaluate(() => performance.now());
}

export async function advanceClockUntil(page: Page, done: () => boolean, stepMs = 250): Promise<void> {
  await expect
    .poll(
      async () => {
        if (!done()) {
          await page.clock.runFor(stepMs);
        }
        return done();
      },
      { intervals: [20] },
    )
    .toBe(true);
}

export async function hintUnderVideo(page: Page, pattern: RegExp): Promise<boolean> {
  const video = await boxOf(monitorPage(page).video);
  const boxes = await Promise.all((await page.getByText(pattern).all()).map((match) => match.boundingBox()));
  return boxes.some(
    (box) =>
      box !== null && box.y >= video.y + video.height - 1 && box.x < video.x + video.width && box.width > 0,
  );
}

const STOPPED_TRACKS_KEY = 'test-stopped-camera-tracks';

export async function recordTrackStops(page: Page): Promise<void> {
  await page.addInitScript((key) => {
    const stop = MediaStreamTrack.prototype.stop;
    MediaStreamTrack.prototype.stop = function stopAndRecord(this: MediaStreamTrack) {
      const stopped: string[] = JSON.parse(sessionStorage.getItem(key) ?? '[]');
      sessionStorage.setItem(key, JSON.stringify([...stopped, this.id]));
      stop.call(this);
    };
  }, STOPPED_TRACKS_KEY);
}

export function stoppedTrackIds(page: Page): Promise<string[]> {
  return page.evaluate((key) => JSON.parse(sessionStorage.getItem(key) ?? '[]') as string[], STOPPED_TRACKS_KEY);
}

export function cameraTrackIds(page: Page): Promise<string[]> {
  return page.evaluate(() =>
    (globalThis as unknown as CameraWindow).cameraSpy.streams.flatMap((stream) => stream.getTracks().map((track) => track.id)),
  );
}

export function endVideoTracks(page: Page): Promise<void> {
  return page.evaluate(() => {
    for (const stream of (globalThis as unknown as CameraWindow).cameraSpy.streams) {
      for (const track of stream.getVideoTracks()) {
        track.dispatchEvent(new Event('ended'));
      }
    }
  });
}

export async function setTabHidden(page: Page, hidden: boolean): Promise<void> {
  await page.evaluate((isHidden) => {
    Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => (isHidden ? 'hidden' : 'visible') });
    Object.defineProperty(document, 'hidden', { configurable: true, get: () => isHidden });
    document.dispatchEvent(new Event('visibilitychange'));
  }, hidden);
}

type TraceSpan = { widthShare: number; rightGapShare: number };

export function waveformSpan(region: Locator): Promise<TraceSpan | null> {
  return region.evaluate((element) => {
    const trace = Array.from(element.querySelectorAll('path')).find(
      (path) => ((path.getAttribute('d') ?? '').match(/[LCQSTAHV]/gi)?.length ?? 0) > 10,
    );
    const surface = trace?.ownerSVGElement;
    if (trace === undefined || surface === null || surface === undefined) {
      return null;
    }
    const line = trace.getBoundingClientRect();
    const area = surface.getBoundingClientRect();
    return {
      widthShare: line.width / area.width,
      rightGapShare: (area.right - line.right) / area.width,
    };
  });
}

export async function settleRendering(page: Page): Promise<void> {
  for (let round = 0; round < 3; round += 1) {
    await page.evaluate(
      () =>
        new Promise<void>((resolve) => {
          const channel = new MessageChannel();
          channel.port1.addEventListener('message', () => resolve());
          channel.port1.start();
          channel.port2.postMessage(null);
        }),
    );
  }
}
