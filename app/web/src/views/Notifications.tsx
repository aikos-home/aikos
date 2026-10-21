// Benachrichtigungen auf diesem Gerät (A24): a new door message as a push, with the recognised text, never sound.
import { useEffect, useState } from "preact/hooks";
import { api } from "../api";
import { pushOff, pushOn, pushState, type PushState } from "../push";

const HINT: Record<PushState, string> = {
  unsupported: "Dieser Browser kann keine Benachrichtigungen empfangen.",
  "needs-install": "Auf dem iPhone kommen Benachrichtigungen nur in der installierten App: Teilen, „Zum Home-Bildschirm“, "
    + "dann von dort öffnen.",
  denied: "Benachrichtigungen sind für aikos blockiert. Erlauben in den Einstellungen des Browsers bzw. des Handys.",
  off: "Neue Nachrichten an der Tür kommen als Benachrichtigung, mit dem erkannten Text. Nur Nachrichten, die du sehen darfst.",
  on: "An: neue Nachrichten an der Tür kommen auf dieses Gerät.",
};

export function Notifications() {
  const [state, setState] = useState<PushState | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  useEffect(() => {
    pushState().then(setState).catch(() => setState("unsupported"));
  }, []);

  const run = async (action: () => Promise<PushState>) => {
    setBusy(true);
    setMsg("");
    try {
      setState(await action());
    } catch (e) {
      setMsg((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const test = async () => {
    setMsg("");
    try {
      const { sent } = await api.pushTest();
      setMsg(sent ? "Test geschickt." : "Kein Gerät hat den Test angenommen.");
    } catch (e) {
      setMsg((e as Error).message);
    }
  };

  if (state === null) return null;
  return (
    <section class="pad">
      <h2>Benachrichtigungen</h2>
      <p class="meta">{HINT[state]}</p>
      <div class="row gap">
        {state === "off" && (
          <button class="primary" onClick={() => run(pushOn)} disabled={busy}>Auf diesem Gerät einschalten</button>
        )}
        {state === "on" && (
          <>
            <button onClick={test}>Test</button>
            <button class="link danger" onClick={() => run(pushOff)} disabled={busy}>Ausschalten</button>
          </>
        )}
      </div>
      {msg && <p class="meta">{msg}</p>}
    </section>
  );
}
