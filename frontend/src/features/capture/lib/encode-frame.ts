export const FRAME_WIDTH = 640
export const FRAME_HEIGHT = 480
export const JPEG_QUALITY = 0.8
const HEADER_BYTES = 8

type Crop = { x: number; y: number; width: number; height: number }

export class FrameCaptureError extends Error {
  constructor(reason: string, options?: ErrorOptions) {
    super(reason, options)
    this.name = "FrameCaptureError"
  }
}

export function centreCrop(sourceWidth: number, sourceHeight: number): Crop {
  const target = FRAME_WIDTH / FRAME_HEIGHT
  if (sourceWidth / sourceHeight > target) {
    const width = sourceHeight * target
    return { x: (sourceWidth - width) / 2, y: 0, width, height: sourceHeight }
  }
  const height = sourceWidth / target
  return { x: 0, y: (sourceHeight - height) / 2, width: sourceWidth, height }
}

export function createFrameCanvas(): HTMLCanvasElement {
  const canvas = document.createElement("canvas")
  canvas.width = FRAME_WIDTH
  canvas.height = FRAME_HEIGHT
  return canvas
}

function toJpeg(canvas: HTMLCanvasElement): Promise<Blob | null> {
  return new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", JPEG_QUALITY))
}

async function drawAndEncode(video: HTMLVideoElement, canvas: HTMLCanvasElement, captureMs: number): Promise<ArrayBuffer> {
  const context = canvas.getContext("2d")
  if (context === null) {
    throw new FrameCaptureError("The canvas gave no 2D context.")
  }
  const crop = centreCrop(video.videoWidth, video.videoHeight)
  context.drawImage(video, crop.x, crop.y, crop.width, crop.height, 0, 0, FRAME_WIDTH, FRAME_HEIGHT)
  const blob = await toJpeg(canvas)
  if (blob === null) {
    throw new FrameCaptureError("The canvas returned no JPEG.")
  }
  const jpeg = new Uint8Array(await blob.arrayBuffer())
  const message = new Uint8Array(HEADER_BYTES + jpeg.byteLength)
  new DataView(message.buffer).setFloat64(0, captureMs, true)
  message.set(jpeg, HEADER_BYTES)
  return message.buffer
}

export async function encodeFrame(
  video: HTMLVideoElement,
  canvas: HTMLCanvasElement,
  captureMs: number,
): Promise<ArrayBuffer | null> {
  if (video.readyState < HTMLMediaElement.HAVE_CURRENT_DATA || video.videoWidth === 0 || video.videoHeight === 0) {
    return null
  }
  try {
    return await drawAndEncode(video, canvas, captureMs)
  } catch (error) {
    throw error instanceof FrameCaptureError ? error : new FrameCaptureError("Encoding the frame threw.", { cause: error })
  }
}
