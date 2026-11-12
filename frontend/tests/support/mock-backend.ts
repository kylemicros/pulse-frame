import { performance } from 'node:perf_hooks';
import type { Page, WebSocketRoute } from '@playwright/test';
import { recordSockets, STREAM_URL } from './socket-recorder';

export { STREAM_URL };

export type PatchName = 'forehead' | 'left_cheek' | 'right_cheek';
type Point = [number, number];
type PatchWire = { usable: boolean; outline: Point[] | null };
type Scene = { face: boolean; moving: boolean; patches: Record<PatchName, PatchWire> };
type ReadingState = 'acquiring' | 'ok' | 'low_quality';
type Reading = { bpm: number | null; quality_db: number | null; state: ReadingState };
type Sample = [number, number];
type WireError = { code: string; message: string; action: string };
type ServerClose = { code: number; reason?: string };

type Connection = {
  id: number;
  openedAt: number;
  closedAt: number | null;
  closedBy: 'page' | 'server' | null;
  closeCode: number | null;
  accepted: boolean;
};

type ReceivedFrame = {
  connection: number;
  arrivedAt: number;
  captureMs: number;
  jpeg: Buffer;
  arrivedWhileAwaitingReply: boolean;
};

export const PATCH_NAMES: PatchName[] = ['forehead', 'left_cheek', 'right_cheek'];

const FOREHEAD: Point[] = [
  [0.4512, 0.2208],
  [0.5507, 0.2196],
  [0.5631, 0.2794],
  [0.4402, 0.281],
];
const LEFT_CHEEK: Point[] = [
  [0.6011, 0.4402],
  [0.665, 0.4721],
  [0.6302, 0.5513],
  [0.5809, 0.5207],
];
const RIGHT_CHEEK: Point[] = [
  [0.3989, 0.4402],
  [0.335, 0.4721],
  [0.3698, 0.5513],
  [0.4191, 0.5207],
];

export function usable(outline: Point[]): PatchWire {
  return { usable: true, outline };
}

export const UNUSABLE: PatchWire = { usable: false, outline: null };

export function faceScene(overrides: Partial<Scene> = {}): Scene {
  return {
    face: true,
    moving: false,
    patches: {
      forehead: usable(FOREHEAD),
      left_cheek: usable(LEFT_CHEEK),
      right_cheek: usable(RIGHT_CHEEK),
    },
    ...overrides,
  };
}

export const NO_FACE_SCENE: Scene = {
  face: false,
  moving: false,
  patches: { forehead: UNUSABLE, left_cheek: UNUSABLE, right_cheek: UNUSABLE },
};

export const WIRE_ERRORS = {
  BAD_FRAME: {
    code: 'BAD_FRAME',
    message: 'The frame could not be read as a capture time followed by a JPEG image of at most 1920 x 1080.',
    action: 'Send each frame as one binary message: the capture time as a little endian float64, then the JPEG image.',
  },
  BAD_TIMESTAMP: {
    code: 'BAD_TIMESTAMP',
    message: "The frame's capture time was not a valid time, was not after the previous frame, or ran too far ahead of it.",
    action: 'Send the performance.now() time at capture with each frame, rising from frame to frame.',
  },
  FRAME_TOO_LARGE: {
    code: 'FRAME_TOO_LARGE',
    message: 'The frame was larger than the 200 KiB limit.',
    action: 'Send JPEG frames at 640 x 480 and quality 0.8 or lower.',
  },
  RATE_LIMITED: {
    code: 'RATE_LIMITED',
    message: 'The frame came too soon: 30 frames were already taken in the last second, so this one was dropped.',
    action: 'Send frames at least 34 ms apart.',
  },
} satisfies Record<string, WireError>;

export function pulseSamples(count: number, endMs = 20000): Sample[] {
  const step = 1000 / 30;
  return Array.from({ length: count }, (_, index) => {
    const t = endMs - (count - 1 - index) * step;
    const value = Math.sin((2 * Math.PI * 1.2 * t) / 1000);
    return [Math.round(t * 10) / 10, Math.round(value * 10000) / 10000];
  });
}

const ACQUIRING: Reading = { bpm: null, quality_db: null, state: 'acquiring' };
const READING_EVERY_MS = 1000;
const REFUSED_BEFORE_OPEN = 1006;

type SentError = { code: string; framesBefore: number };

type DuplicateTiming = 'during-spacing-wait' | 'after-next-frame';

type SentDuplicate = { timing: DuplicateTiming; framesBefore: number; at: number };

type Stream = {
  connection: Connection;
  awaitingReply: boolean;
  lastReadingT: number | null;
  staleReply: string | null;
};

export class MockBackend {
  readonly connections: Connection[] = [];
  readonly frames: ReceivedFrame[] = [];
  readonly textMessages: string[] = [];
  readonly sentErrors: SentError[] = [];
  readonly flashedAtFrames: number[] = [];
  private refusal: ServerClose | null = null;
  private scene: Scene = faceScene();
  private flash: Scene | null = null;
  private pendingReading: { reading: Reading; samples: Sample[] } | null = null;
  private pendingError: { error: WireError; holdAfter: boolean } | null = null;
  private pendingUnreadable: { text: string; holdAfter: boolean } | null = null;
  private held = false;
  private readonly heldTurns: Array<() => void> = [];
  private replyDelayMs = 0;
  private duplicate: DuplicateTiming | null = null;
  readonly sentDuplicates: SentDuplicate[] = [];

  static async attach(page: Page): Promise<MockBackend> {
    await recordSockets(page);
    const backend = new MockBackend();
    await page.routeWebSocket(STREAM_URL, (ws) => backend.connect(ws));
    return backend;
  }

  refuseEveryConnection(close: ServerClose): void {
    this.refusal = close;
  }

  acceptEveryConnection(): void {
    this.refusal = null;
  }

  setScene(scene: Scene): void {
    this.scene = scene;
  }

  flashScene(scene: Scene): void {
    this.flash = scene;
  }

  pushReading(reading: Reading, samples: Sample[] = pulseSamples(300)): void {
    this.pendingReading = { reading, samples };
  }

  replyNextWithError(error: WireError, options: { holdAfter: boolean } = { holdAfter: false }): void {
    this.pendingError = { error, holdAfter: options.holdAfter };
  }

  sendUnreadableNext(text: string, options: { holdAfter: boolean } = { holdAfter: false }): void {
    this.pendingUnreadable = { text, holdAfter: options.holdAfter };
  }

  duplicateNextReply(timing: DuplicateTiming): void {
    this.duplicate = timing;
  }

  setReplyDelay(ms: number): void {
    this.replyDelayMs = ms;
  }

  releaseReplies(): void {
    this.held = false;
    for (const turn of this.heldTurns.splice(0)) {
      turn();
    }
  }

  openConnections(): Connection[] {
    return this.connections.filter((connection) => connection.accepted && connection.closedAt === null);
  }

  framesOn(connectionId: number): ReceivedFrame[] {
    return this.frames.filter((frame) => frame.connection === connectionId);
  }

  private connect(ws: WebSocketRoute): void {
    const connection: Connection = {
      id: this.connections.length + 1,
      openedAt: performance.now(),
      closedAt: null,
      closedBy: null,
      closeCode: null,
      accepted: false,
    };
    this.connections.push(connection);
    ws.onClose((code) => {
      if (connection.closedAt === null) {
        connection.closedAt = performance.now();
        connection.closedBy = 'page';
        connection.closeCode = code ?? null;
      }
    });
    if (this.refusal !== null) {
      this.closeFromServer(ws, connection, this.refusal);
      return;
    }
    if (this.openConnections().length > 0) {
      this.closeFromServer(ws, connection, { code: 1013, reason: 'ANOTHER_CONNECTION_OPEN' });
      return;
    }
    connection.accepted = true;
    const stream: Stream = { connection, awaitingReply: false, lastReadingT: null, staleReply: null };
    ws.onMessage((message) => {
      if (typeof message === 'string') {
        this.textMessages.push(message);
        ws.send(JSON.stringify({ type: 'error', ...WIRE_ERRORS.BAD_FRAME }));
        return;
      }
      const captureMs = message.readDoubleLE(0);
      this.frames.push({
        connection: connection.id,
        arrivedAt: performance.now(),
        captureMs,
        jpeg: message.subarray(8),
        arrivedWhileAwaitingReply: stream.awaitingReply,
      });
      stream.awaitingReply = true;
      if (stream.staleReply !== null) {
        const stale = stream.staleReply;
        stream.staleReply = null;
        this.sendDuplicate(ws, stale, 'after-next-frame');
      }
      const turn = () => this.replyTurn(ws, stream, Math.floor(captureMs));
      if (this.held) {
        this.heldTurns.push(turn);
      } else if (this.replyDelayMs > 0) {
        setTimeout(turn, this.replyDelayMs);
      } else {
        turn();
      }
    });
  }

  private replyTurn(ws: WebSocketRoute, stream: Stream, t: number): void {
    if (stream.connection.closedAt !== null) {
      return;
    }
    if (this.pendingError !== null) {
      const { error, holdAfter } = this.pendingError;
      this.pendingError = null;
      this.sentErrors.push({ code: error.code, framesBefore: this.frames.length });
      stream.awaitingReply = false;
      ws.send(JSON.stringify({ type: 'error', ...error }));
      this.held = this.held || holdAfter;
      return;
    }
    if (this.pendingUnreadable !== null) {
      const { text, holdAfter } = this.pendingUnreadable;
      this.pendingUnreadable = null;
      ws.send(text);
      if (holdAfter) {
        this.held = true;
        this.heldTurns.push(() => this.replyTurn(ws, stream, t));
        return;
      }
    }
    if (stream.lastReadingT === null) {
      this.sendReading(ws, t, ACQUIRING, []);
      stream.lastReadingT = t;
    } else if (this.pendingReading !== null && t - stream.lastReadingT >= READING_EVERY_MS) {
      const { reading, samples } = this.pendingReading;
      this.pendingReading = null;
      this.sendReading(ws, t, reading, samples);
      stream.lastReadingT = t;
    }
    const scene = this.flash ?? this.scene;
    if (this.flash !== null) {
      this.flash = null;
      this.flashedAtFrames.push(this.frames.length);
    }
    stream.awaitingReply = false;
    const reply = JSON.stringify({ type: 'frame', t, ...scene });
    ws.send(reply);
    const timing = this.duplicate;
    this.duplicate = null;
    if (timing === 'during-spacing-wait') {
      this.sendDuplicate(ws, reply, timing);
    } else if (timing === 'after-next-frame') {
      stream.staleReply = reply;
    }
  }

  private sendDuplicate(ws: WebSocketRoute, reply: string, timing: DuplicateTiming): void {
    this.sentDuplicates.push({ timing, framesBefore: this.frames.length, at: performance.now() });
    ws.send(reply);
  }

  private sendReading(ws: WebSocketRoute, t: number, reading: Reading, samples: Sample[]): void {
    ws.send(JSON.stringify({ type: 'pulse', samples }));
    ws.send(JSON.stringify({ type: 'bpm', t, ...reading }));
  }

  private closeFromServer(ws: WebSocketRoute, connection: Connection, close: ServerClose): void {
    const shut = () => {
      if (connection.closedAt !== null) {
        return;
      }
      connection.closedAt = performance.now();
      connection.closedBy = 'server';
      connection.closeCode = close.code;
      void ws.close({ code: close.code, reason: close.reason ?? '' });
    };
    if (close.code === REFUSED_BEFORE_OPEN) {
      shut();
    } else {
      setTimeout(shut, 0);
    }
  }
}
