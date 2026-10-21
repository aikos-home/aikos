// Sign in: one button, the phone asks for the fingerprint/face/PIN. No user name, no password.
import { useState } from "preact/hooks";
import type { User } from "../api";
import { errorText, login, passkeysAvailable } from "../passkey";
import { NoPasskeys, Welcome } from "./Welcome";

export function Login({ onDone }: { onDone: (u: User) => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const go = async () => {
    setBusy(true);
    setError("");
    try {
      onDone(await login());
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Welcome title="aikos">
      {!passkeysAvailable() && <NoPasskeys />}
      <button class="primary wide" onClick={go} disabled={busy}>
        {busy ? "Warte auf den Passkey …" : "Mit Passkey anmelden"}
      </button>
      {error && <p class="error">{error}</p>}
      <p class="muted small">Noch kein Zugang? Lass dir eine Einladung schicken.</p>
    </Welcome>
  );
}
