import { CameraUnsupportedError } from "@/features/capture/lib/camera-errors"

const CAMERA_CONSTRAINTS: MediaStreamConstraints = {
  audio: false,
  video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: "user" },
}

export function openCamera(): Promise<MediaStream> {
  const devices: MediaDevices | undefined = navigator.mediaDevices
  if (devices === undefined || typeof devices.getUserMedia !== "function") {
    return Promise.reject(new CameraUnsupportedError())
  }
  return devices.getUserMedia(CAMERA_CONSTRAINTS)
}

export function stopCamera(stream: MediaStream): void {
  for (const track of stream.getTracks()) {
    track.stop()
  }
}
