// Invite link (/einladung#token): shows who it is for, then creates the passkey for that person or device.
import { useEffect, useState } from "preact/hooks";
import { api, ROLE_NAMES, type Role, type User } from "../api";
import { errorText, passkeysAvailable, redeemInvite } from "../passkey";
import { NoPasskeys, Welcome } from "./Welcome";

export function Invite({ token, onDone, onLogin }: { token: string; onDone: (u: User) => void; onLogin: () => void }) {
  const [info, setInfo] = useState<{ name: string; role: Role; kind: "new" | "device" } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api.inviteInfo(token).then(setInfo).catch((e) => setError(errorText(e)));
  }, [token]);

  const go = async () => {
    setBusy(true);
    setError("");
    try {
      onDone(await redeemInvite(token));
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Welcome title={info ? `Hallo ${info.name}` : "Einladung"}>
      {info && (
        <p class="muted">
          {info.kind === "new"
            ? `Du bist zu aikos eingeladen (${ROLE_NAMES[info.role]}). Lege jetzt deinen Passkey an. Danach meldest du dich nur noch mit Fingerabdruck, Gesicht oder PIN an.`
            : "Lege einen Passkey für dieses Gerät an."}
        </p>
      )}
      {!passkeysAvailable() && <NoPasskeys />}
      {info && (
        <button class="primary wide" onClick={go} disabled={busy}>
          {busy ? "Warte auf den Passkey …" : "Passkey anlegen"}
        </button>
      )}
      {error && <p class="error">{error}</p>}
      <button class="link" onClick={onLogin}>Ich habe schon einen Passkey</button>
    </Welcome>
  );
}
