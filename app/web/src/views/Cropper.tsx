// Crop a photo for the door (A12): a fixed frame in the door's aspect (492 × 536), so the picture fills the field there.
// Drag to move, pinch or the slider to zoom; the preview is grey, as the door shows it. The result is exactly 2× the field.
import { useEffect, useRef, useState } from "preact/hooks";

export const FIELD_W = 492;
export const FIELD_H = 536;
const OUT_SCALE = 2;          // sharper than the field; the door's side reduces it
const MAX_ZOOM = 4;

type View = { zoom: number; x: number; y: number };  // zoom 1 = the photo just covers the frame; x/y = photo centre offset

function clampView(v: View, img: ImageBitmap, fw: number, fh: number): View {
  const zoom = Math.max(1, Math.min(MAX_ZOOM, v.zoom));
  const cover = Math.max(fw / img.width, fh / img.height) * zoom;
  const maxX = Math.max(0, (img.width * cover - fw) / 2);
  const maxY = Math.max(0, (img.height * cover - fh) / 2);
  return { zoom, x: Math.max(-maxX, Math.min(maxX, v.x)), y: Math.max(-maxY, Math.min(maxY, v.y)) };
}

function draw(ctx: CanvasRenderingContext2D, img: ImageBitmap, v: View, w: number, h: number, frameW: number) {
  const k = w / frameW;                                            // the same view at another size
  const s = Math.max(frameW / img.width, (frameW * FIELD_H / FIELD_W) / img.height) * v.zoom * k;
  ctx.fillStyle = "#fff";
  ctx.fillRect(0, 0, w, h);
  ctx.imageSmoothingQuality = "high";
  ctx.drawImage(img, w / 2 + v.x * k - (img.width * s) / 2, h / 2 + v.y * k - (img.height * s) / 2, img.width * s, img.height * s);
}

export function Cropper({ file, onDone, onCancel }: { file: File; onDone: (blob: Blob) => void; onCancel: () => void }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const [img, setImg] = useState<ImageBitmap | null>(null);
  const [view, setView] = useState<View>({ zoom: 1, x: 0, y: 0 });
  const [error, setError] = useState("");
  const pointers = useRef(new Map<number, { x: number; y: number }>());
  const pinch = useRef<{ dist: number; zoom: number } | null>(null);
  const frameW = Math.min(320, window.innerWidth - 48);
  const frameH = Math.round(frameW * FIELD_H / FIELD_W);

  useEffect(() => {
    let bitmap: ImageBitmap | null = null;
    createImageBitmap(file, { imageOrientation: "from-image" })
      .then((b) => {
        bitmap = b;
        setImg(b);
        setView({ zoom: 1, x: 0, y: 0 });
      })
      .catch(() => setError("Das ist kein Bild, das der Browser lesen kann."));
    return () => bitmap?.close();
  }, [file]);

  useEffect(() => {
    const c = canvas.current;
    if (!c || !img) return;
    const dpr = window.devicePixelRatio || 1;
    c.width = Math.round(frameW * dpr);
    c.height = Math.round(frameH * dpr);
    draw(c.getContext("2d")!, img, view, c.width, c.height, frameW);
  }, [img, view, frameW, frameH]);

  const set = (v: View) => img && setView(clampView(v, img, frameW, frameH));

  const down = (e: PointerEvent) => {
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    pointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pointers.current.size === 2) {
      const [a, b] = [...pointers.current.values()];
      pinch.current = { dist: Math.hypot(a.x - b.x, a.y - b.y), zoom: view.zoom };
    }
  };
  const move = (e: PointerEvent) => {
    const prev = pointers.current.get(e.pointerId);
    if (!prev) return;
    pointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pointers.current.size === 2 && pinch.current) {
      const [a, b] = [...pointers.current.values()];
      set({ ...view, zoom: pinch.current.zoom * Math.hypot(a.x - b.x, a.y - b.y) / pinch.current.dist });
    } else if (pointers.current.size === 1) {
      set({ ...view, x: view.x + e.clientX - prev.x, y: view.y + e.clientY - prev.y });
    }
  };
  const up = (e: PointerEvent) => {
    pointers.current.delete(e.pointerId);
    if (pointers.current.size < 2) pinch.current = null;
  };
  const wheel = (e: WheelEvent) => {
    e.preventDefault();
    set({ ...view, zoom: view.zoom * (e.deltaY < 0 ? 1.1 : 1 / 1.1) });
  };

  const take = () => {
    if (!img) return;
    const out = document.createElement("canvas");
    out.width = FIELD_W * OUT_SCALE;
    out.height = FIELD_H * OUT_SCALE;
    draw(out.getContext("2d")!, img, view, out.width, out.height, frameW);
    out.toBlob((b) => (b ? onDone(b) : setError("Das Bild ließ sich nicht umrechnen.")), "image/jpeg", 0.88);
  };

  if (error) return <p class="error">{error} <button class="link" onClick={onCancel}>Zurück</button></p>;
  return (
    <div class="cropper">
      <canvas ref={canvas} style={{ width: `${frameW}px`, height: `${frameH}px` }} class="crop-frame"
              onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerCancel={up} onWheel={wheel} />
      <p class="meta">Ziehen zum Verschieben, mit zwei Fingern oder dem Regler zoomen. So füllt es das Feld an der Tür ({FIELD_W} × {FIELD_H}).</p>
      <label class="zoom">Zoom
        <input type="range" min={1} max={MAX_ZOOM} step={0.01} value={view.zoom}
               onInput={(e) => set({ ...view, zoom: Number(e.currentTarget.value) })} />
      </label>
      <div class="row gap">
        <button class="primary" disabled={!img} onClick={take}>An die Tür</button>
        <button class="link" onClick={onCancel}>Abbrechen</button>
      </div>
    </div>
  );
}
