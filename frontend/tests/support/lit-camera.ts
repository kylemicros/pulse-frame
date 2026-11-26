import type { Page } from '@playwright/test';
import {
  SETUP_BRIGHTNESS_MAX,
  SETUP_BRIGHTNESS_MIN,
  SETUP_NEAR_WHITE,
} from '../../src/features/guided-capture/lib/setup-check';
import { faceScene, FRAME_HEIGHT_PX, FRAME_WIDTH_PX, outlinePoints } from './mock-backend';

export type Light = 'even' | 'behind' | 'behind-dark' | 'dark' | 'bright';

type Shade = { face: number; around: number };

type Box = { left: number; top: number; right: number; bottom: number };

type LitWindow = Window & { litCamera: { show: (shade: Shade) => void } };

const WHITE = 255;

const MID = Math.round((SETUP_BRIGHTNESS_MIN + SETUP_BRIGHTNESS_MAX) / 2);
const DIM = Math.floor(SETUP_BRIGHTNESS_MIN / 2);
const GLARE = Math.round((SETUP_BRIGHTNESS_MAX + SETUP_NEAR_WHITE) / 2);
const SOFT = Math.round((SETUP_BRIGHTNESS_MIN + MID) / 2);

export const SHADES: Record<Light, Shade> = {
  even: { face: MID, around: SOFT },
  behind: { face: MID, around: WHITE },
  'behind-dark': { face: DIM, around: WHITE },
  dark: { face: DIM, around: DIM },
  bright: { face: GLARE, around: SOFT },
};

function defaultFaceBox(): Box {
  const points = outlinePoints(faceScene());
  const xs = points.map(([x]) => x);
  const ys = points.map(([, y]) => y);
  return { left: Math.min(...xs), top: Math.min(...ys), right: Math.max(...xs), bottom: Math.max(...ys) };
}

export async function installLitCamera(page: Page, light: Light): Promise<void> {
  await page.addInitScript(
    ({ box, shade, width, height }) => {
      let current = shade;
      const surfaces: Array<{ context: CanvasRenderingContext2D; stream: MediaStream }> = [];
      const paint = (surface: { context: CanvasRenderingContext2D; stream: MediaStream }) => {
        const { context, stream } = surface;
        const { face, around } = current;
        context.fillStyle = `rgb(${around}, ${around}, ${around})`;
        context.fillRect(0, 0, width, height);
        context.fillStyle = `rgb(${face}, ${face}, ${face})`;
        context.fillRect(
          Math.floor(box.left * width),
          Math.floor(box.top * height),
          Math.ceil((box.right - box.left) * width),
          Math.ceil((box.bottom - box.top) * height),
        );
        for (const track of stream.getVideoTracks()) {
          (track as MediaStreamTrack & { requestFrame?: () => void }).requestFrame?.();
        }
      };
      Object.defineProperty(globalThis, 'litCamera', {
        value: {
          show: (next: { face: number; around: number }) => {
            current = next;
            surfaces.forEach(paint);
          },
        },
      });
      navigator.mediaDevices.getUserMedia = async () => {
        const canvas = document.createElement('canvas');
        canvas.width = width;
        canvas.height = height;
        const context = canvas.getContext('2d');
        if (context === null) {
          throw new Error('The lit camera got no 2D context');
        }
        const surface = { context, stream: canvas.captureStream(0) };
        surfaces.push(surface);
        paint(surface);
        return surface.stream;
      };
    },
    { box: defaultFaceBox(), shade: SHADES[light], width: FRAME_WIDTH_PX, height: FRAME_HEIGHT_PX },
  );
}

export function showLight(page: Page, light: Light): Promise<void> {
  return page.evaluate((shade) => (globalThis as unknown as LitWindow).litCamera.show(shade), SHADES[light]);
}
