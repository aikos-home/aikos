// Sound from the phone for the door: the greeting and one's own voice are recorded with the phone's microphone.
// (Photos are cropped to the door's field in views/Cropper.tsx.)

export const RECORD_MAX_S = 20;

const TYPES = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"];

export class Recorder {
  private rec: MediaRecorder | null = null;
  private chunks: Blob[] = [];
  private timer = 0;

  static supported(): boolean {
    return typeof MediaRecorder !== "undefined" && !!navigator.mediaDevices?.getUserMedia;
  }

  /** `bits`: the recording's bit rate (a voice message stays small); the browser's own without. */
  async start(onDone: (blob: Blob) => void, maxS = RECORD_MAX_S, bits?: number): Promise<void> {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
    const mimeType = TYPES.find((t) => MediaRecorder.isTypeSupported(t));
    this.rec = new MediaRecorder(stream, { ...(mimeType ? { mimeType } : {}), ...(bits ? { audioBitsPerSecond: bits } : {}) });
    this.chunks = [];
    this.rec.ondataavailable = (e) => e.data.size && this.chunks.push(e.data);
    this.rec.onstop = () => {
      stream.getTracks().forEach((t) => t.stop());
      clearTimeout(this.timer);
      onDone(new Blob(this.chunks, { type: (this.rec?.mimeType || "audio/webm").split(";")[0] }));
    };
    this.rec.start();
    this.timer = window.setTimeout(() => this.stop(), maxS * 1000);
  }

  stop(): void {
    if (this.rec && this.rec.state !== "inactive") this.rec.stop();
  }
}
