// Small display helpers (German).

export function when(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const today = new Date();
  const yesterday = new Date(today.getTime() - 86_400_000);
  const hm = d.toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" });
  if (d.toDateString() === today.toDateString()) return `heute ${hm}`;
  if (d.toDateString() === yesterday.toDateString()) return `gestern ${hm}`;
  return `${d.toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit" })} ${hm}`;
}

export function clock(epochSeconds: number | null): string {
  if (!epochSeconds) return "";
  return new Date(epochSeconds * 1000).toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" });
}

export function duration(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds)) return "";
  const s = Math.round(seconds);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/** "Paketdienst · DHL: Ich habe …" → speaker and words (older messages; the register delivers both as fields). */
export function splitSpeaker(text: string): { speaker: string; words: string } {
  const i = text.indexOf(": ");
  if (i > 0 && i <= 40) return { speaker: text.slice(0, i), words: text.slice(i + 2) };
  return { speaker: "", words: text };
}

export function hhmm(value: string): string {
  return value ? value.slice(0, 5) : "";
}
