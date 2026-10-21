// A one-time link for another device: as QR code to scan with the phone, plus share/copy. Black on white, always.
import { useEffect, useRef, useState } from "preact/hooks";
import qrcode from "qrcode-generator";

const MARGIN = 4;

export function QrCode({ text, size = 220 }: { text: string; size?: number }) {
  const qr = qrcode(0, "M");
  qr.addData(text);
  qr.make();
  const n = qr.getModuleCount();
  const total = n + 2 * MARGIN;
  let d = "";
  for (let r = 0; r < n; r++) {
    for (let c = 0; c < n; c++) {
      if (qr.isDark(r, c)) d += `M${c + MARGIN} ${r + MARGIN}h1v1h-1z`;
    }
  }
  return (
    <svg class="qr" viewBox={`0 0 ${total} ${total}`} width={size} height={size} role="img" aria-label="QR-Code"
         shape-rendering="crispEdges">
      <rect width={total} height={total} fill="#fff" />
      <path d={d} fill="#000" />
    </svg>
  );
}

export function LinkPanel({ link, title, hint, onClose }: { link: string; title: string; hint: string; onClose: () => void }) {
  const box = useRef<HTMLDivElement>(null);
  const [msg, setMsg] = useState("");
  useEffect(() => box.current?.scrollIntoView({ behavior: "smooth", block: "center" }), [link]);

  const share = async () => {
    const nav: Navigator = navigator;
    try {
      if (typeof nav.share === "function") await nav.share({ title: "aikos", text: title, url: link });
      else {
        await nav.clipboard.writeText(link);
        setMsg("Link kopiert.");
      }
    } catch {
      // closing the share sheet is fine
    }
  };
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(link);
      setMsg("Link kopiert.");
    } catch {
      setMsg("Kopieren ging nicht; der Link steht unter dem Code.");
    }
  };

  return (
    <div class="linkpanel" ref={box}>
      <strong>{title}</strong>
      <QrCode text={link} />
      <p class="meta">{hint}</p>
      <div class="row gap">
        <button onClick={share}>Teilen</button>
        <button onClick={copy}>Link kopieren</button>
        <button class="link" onClick={onClose}>Schließen</button>
      </div>
      {msg && <p class="meta">{msg}</p>}
      <code class="break small">{link}</code>
    </div>
  );
}
