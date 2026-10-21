// Forward a door message by hand (A37): text and MP3 into the app the phone offers (WhatsApp, Signal, mail …).
// Only when a resident taps "Teilen"; aikos itself never sends sound out of the house (R11).
import { ApiError, type DoorMessage } from "./api";
import { duration, when } from "./format";

export type ShareResult = "shared" | "saved" | "cancelled" | "needs-tap";

export function shareText(m: DoorMessage, speaker: string, words: string): string {
  const head = ["Nachricht an der Tür", when(m.time), duration(m.seconds), m.recipient ? `für ${m.recipient}` : ""]
    .filter(Boolean).join(" · ");
  const said = words ? `„${words}“${speaker ? ` (${speaker})` : ""}` : "";
  return said ? `${head}\n${said}` : head;
}

/** The MP3 through the app (the server records the forwarding). */
export async function shareFile(m: DoorMessage): Promise<File> {
  let response: Response;
  try {
    response = await fetch(`${m.audio}?share=1`, { credentials: "same-origin" });
  } catch {
    throw new ApiError("network", 0);
  }
  if (!response.ok) throw new ApiError(response.status === 404 ? "not_found" : "ha_error", response.status);
  return new File([await response.blob()], `aikos-${m.id}.mp3`, { type: m.content_type || "audio/mpeg" });
}

/** Share sheet with file and text; where files can't be shared (desktop browsers) the MP3 is saved and the text copied.
 * "needs-tap": the browser wants a fresh tap (the download took too long for its gesture window). */
export async function share(file: File, text: string): Promise<ShareResult> {
  const data = { files: [file], text, title: "Nachricht an der Tür" };
  if (typeof navigator.canShare === "function" && navigator.canShare(data)) {
    try {
      await navigator.share(data);
      return "shared";
    } catch (e) {
      const name = (e as DOMException).name;
      if (name === "AbortError") return "cancelled";
      if (name === "NotAllowedError") return "needs-tap";
      throw e;
    }
  }
  const url = URL.createObjectURL(file);
  const a = document.createElement("a");
  a.href = url;
  a.download = file.name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    // the file is saved; the text is on the card
  }
  return "saved";
}
