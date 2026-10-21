// First start: the one-time setup code from the server plus a name → the first passkey, the superadmin.
import { useState } from "preact/hooks";
import type { User } from "../api";
import { errorText, passkeysAvailable, setup } from "../passkey";
import { NoPasskeys, Welcome } from "./Welcome";

export function Setup({ onDone }: { onDone: (u: User) => void }) {
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const submit = async (e: Event) => {
    e.preventDefault();
    if (!code.trim() || !name.trim()) return setError("Bitte Code und Namen eingeben.");
    setBusy(true);
    setError("");
    try {
      onDone(await setup(code.trim(), name.trim()));
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Welcome title="aikos einrichten">
      <p class="muted">
        Du bist die erste Person. Den Einrichtungscode findest du im Datenordner des aikos-Dienstes
        (<code>setup-code.txt</code>) oder mit <code>python -m aikos_app setup-code</code>.
      </p>
      {!passkeysAvailable() && <NoPasskeys />}
      <form onSubmit={submit} class="stack">
        <label>
          Einrichtungscode
          <input value={code} onInput={(e) => setCode(e.currentTarget.value)} autocomplete="one-time-code"
                 placeholder="ABCD-EFGH-JKLM" />
        </label>
        <label>
          Dein Name
          <input value={name} onInput={(e) => setName(e.currentTarget.value)} autocomplete="name" maxLength={40} />
        </label>
        {error && <p class="error">{error}</p>}
        <button class="primary" disabled={busy}>{busy ? "Warte auf den Passkey …" : "Passkey anlegen"}</button>
      </form>
    </Welcome>
  );
}
