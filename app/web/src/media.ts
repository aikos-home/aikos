// Photos and sound from the phone for the door: the photo is shrunk on the phone (the app takes at most 900 KB, the door
// shows 492×536 grey anyway); the greeting is recorded with the phone's microphone (at most 20 s).

const MAX_SIDE = 1280;
const MAX_BYTES = 880 * 1024;
export const RECORD_MAX_S = 20;

function canvasBlob(canvas: HTMLCanvasElement, quality: number): Promise<Blob> {
  return new Promise((ok, bad) => canvas.toBlob((b) => (b ? ok(b) : bad(new Error("Das Bild ließ sich nicht umrechnen."))),
    "image/jpeg", quality));
}

export async function shrinkPhoto(file: File): Promise<Blob> {
  const bitmap = await createImageBitmap(file, { imageOrientation: "from-image" }).catch(() => {
    throw new Error("Das ist kein Bild, das der Browser lesen kann.");
  });
  const scale = Math.min(1, MAX_SIDE / Math.max(bitmap.width, bitmap.height));
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(bitmap.width * scale);
  canvas.height = Math.round(bitmap.height * scale);
  canvas.getContext("2d")!.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  bitmap.close();
  for (const quality of [0.85, 0.7, 0.55, 0.4]) {
    const blob = await canvasBlob(canvas, quality);
    if (blob.size <= MAX_BYTES) return blob;
  }
  throw new Error("Das Bild ist auch verkleinert noch zu groß.");
}

const TYPES = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"];

export class Recorder {
  private rec: MediaRecorder | null = null;
  private chunks: Blob[] = [];
  private timer = 0;

  static supported(): boolean {
    return typeof MediaRecorder !== "undefined" && !!navigator.mediaDevices?.getUserMedia;
  }

  async start(onDone: (blob: Blob) => void): Promise<void> {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
    const mimeType = TYPES.find((t) => MediaRecorder.isTypeSupported(t));
    this.rec = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
    this.chunks = [];
    this.rec.ondataavailable = (e) => e.data.size && this.chunks.push(e.data);
    this.rec.onstop = () => {
      stream.getTracks().forEach((t) => t.stop());
      clearTimeout(this.timer);
      onDone(new Blob(this.chunks, { type: (this.rec?.mimeType || "audio/webm").split(";")[0] }));
    };
    this.rec.start();
    this.timer = window.setTimeout(() => this.stop(), RECORD_MAX_S * 1000);
  }

  stop(): void {
    if (this.rec && this.rec.state !== "inactive") this.rec.stop();
  }
}
