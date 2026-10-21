// What the sections of the Tür page share: the collapsible section, an action with busy/message state, time labels.
import { useState } from "preact/hooks";
import { Icon } from "./Icon";

export const hm = (iso: string) => {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" });
};
export const dayHm = (iso: string) => {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const today = new Date().toDateString() === d.toDateString();
  return today ? `heute ${hm(iso)}` : `${d.toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit" })} ${hm(iso)}`;
};

export function Section({ icon, title, extra, children }: { icon: string; title: string; extra?: preact.ComponentChildren;
  children: preact.ComponentChildren }) {
  return (
    <details class="section" open>
      <summary><Icon name={icon} /><span>{title}</span><span class="grow" />{extra}</summary>
      <div class="body">{children}</div>
    </details>
  );
}

export function useAction(done: () => void) {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  // fn may return the message to show (e.g. "now" or "waiting"); otherwise `ok` is shown
  const run = async (fn: () => Promise<unknown>, ok = "") => {
    setBusy(true);
    setMsg("");
    try {
      const said = await fn();
      setMsg(typeof said === "string" ? said : ok);
      done();
    } catch (e) {
      setMsg((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return { busy, msg, setMsg, run };
}
