import type { Page } from '@playwright/test';

export const STREAM_URL = 'ws://127.0.0.1:8000/ws/stream';

type SocketMessage = { at: number; text: string };

type SocketRecord = {
  url: string;
  createdAt: number;
  openedAt: number | null;
  closedAt: number | null;
  closeCode: number | null;
  messages: SocketMessage[];
};

type RecorderWindow = Window & { socketRecords: SocketRecord[] };

export type FrameSend = { order: number; at: number; captureMs: number };

type SendLog = { order: number; sends: FrameSend[] };

type SendLogWindow = Window & { frameTiming?: SendLog };

export async function recordSockets(page: Page): Promise<void> {
  await page.addInitScript(() => {
    const records: SocketRecord[] = [];
    Object.defineProperty(globalThis, 'socketRecords', { value: records });
    const wrap = (Base: typeof WebSocket): typeof WebSocket =>
      class RecordedSocket extends Base {
        constructor(url: string | URL, protocols?: string | string[]) {
          super(url, protocols);
          const record: SocketRecord = {
            url: String(url),
            createdAt: performance.now(),
            openedAt: null,
            closedAt: null,
            closeCode: null,
            messages: [],
          };
          records.push(record);
          this.addEventListener('open', () => {
            record.openedAt = performance.now();
          });
          this.addEventListener('close', (event) => {
            record.closedAt = performance.now();
            record.closeCode = event.code;
          });
          this.addEventListener('message', (event) => {
            if (typeof event.data === 'string') {
              record.messages.push({ at: performance.now(), text: event.data });
            }
          });
        }

        override send(data: string | ArrayBufferLike | Blob | ArrayBufferView): void {
          const log = (globalThis as unknown as SendLogWindow).frameTiming;
          if (log !== undefined && data instanceof ArrayBuffer && data.byteLength >= 8) {
            log.order += 1;
            log.sends.push({ order: log.order, at: performance.now(), captureMs: new DataView(data).getFloat64(0, true) });
          }
          super.send(data);
        }
      };
    let current = wrap(globalThis.WebSocket);
    Object.defineProperty(globalThis, 'WebSocket', {
      configurable: true,
      get: () => current,
      set: (value: typeof WebSocket) => {
        current = wrap(value);
      },
    });
  });
}

export function socketRecords(page: Page): Promise<SocketRecord[]> {
  return page.evaluate(
    (url) => (globalThis as unknown as RecorderWindow).socketRecords.filter((record) => record.url === url),
    STREAM_URL,
  );
}

export function lastFrameReplyT(page: Page): Promise<number | null> {
  return page.evaluate((url) => {
    const record = (globalThis as unknown as RecorderWindow).socketRecords.findLast((each) => each.url === url);
    const last = record?.messages.at(-1);
    if (last === undefined) {
      return null;
    }
    const fields: unknown = JSON.parse(last.text);
    return typeof fields === 'object' && fields !== null && 'type' in fields && fields.type === 'frame' && 't' in fields
      ? Number(fields.t)
      : null;
  }, STREAM_URL);
}

function parsed(text: string): Record<string, unknown> | null {
  try {
    const value: unknown = JSON.parse(text);
    return typeof value === 'object' && value !== null ? (value as Record<string, unknown>) : null;
  } catch {
    return null;
  }
}

export function firstMessageAfter(
  records: SocketRecord[],
  since: number,
  matches: (message: Record<string, unknown>) => boolean,
): SocketMessage | null {
  for (const record of records) {
    for (const message of record.messages) {
      const fields = parsed(message.text);
      if (message.at >= since && fields !== null && matches(fields)) {
        return message;
      }
    }
  }
  return null;
}
