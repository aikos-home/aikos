// Tür: what a resident does at the door (A11–A14, A39–A41), as collapsible sections: the bell (mute for a while, quiet
// hours), the picture on the door, the greeting for everyone who comes, the announcements after a ring (sprachausgabe
// S10–S14). On top: the door as a chat (A47–A49), where the push on a ring leads; writing to the door happens there.
import { useEffect, useRef, useState } from "preact/hooks";
import { api, can, type DoorActionsState, type DoorStatus, type User } from "../api";
import { Recorder, RECORD_MAX_S } from "../media";
import { Announcements } from "./Announcements";
import { Call } from "./Call";
import { Cropper } from "./Cropper";
import { dayHm, Section, useAction } from "./DoorParts";
import { Icon } from "./Icon";

const MUTE_FOR: { label: string; body: { minutes?: number; until_time?: string; forever?: boolean } }[] = [
  { label: "1 Std", body: { minutes: 60 } },
  { label: "2 Std", body: { minutes: 120 } },
  { label: "bis morgen 7:00", body: { until_time: "07:00" } },
  { label: "bis ich ausschalte", body: { forever: true } },
];

// <input type="datetime-local"> works in local time without zone
const toLocalInput = (iso: string) => {
  const d = new Date(iso);
  if (!iso || Number.isNaN(d.getTime())) return "";
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
};
const fromLocalInput = (v: string) => (v ? new Date(v).toISOString() : "");

type Props = { user: User; status: DoorStatus | null; refresh: () => void };

export function Door({ user, status, refresh }: Props) {
  const [state, setState] = useState<DoorActionsState | null | undefined>(undefined);
  const [error, setError] = useState("");
  const load = () => api.doorActions().then(setState).catch((e) => setError(e.message));
  useEffect(() => {
    load();
    const t = setInterval(load, 10_000);
    return () => clearInterval(t);
  }, []);
  const after = () => {
    load();
    refresh();
  };

  if (!can(user, "door.act") && !can(user, "bell.settings")) return <p class="muted pad">Für dich gibt es hier nichts.</p>;
  if (state === undefined) return <p class="muted pad">Lade …</p>;
  if (state === null) return <p class="muted pad">Dafür braucht Home Assistant die aikos-Integration ab 0.9.0.</p>;
  return (
    <div class="door">
      {error && <p class="error pad">{error}</p>}
      {can(user, "door.act") && <Call state={state} me={user.name} here={!!status?.someone_at_door} done={after} />}
      {can(user, "bell.settings") && <Bell status={status} done={after} />}
      {can(user, "door.act") && <Picture state={state} done={after} />}
      {can(user, "door.act") && <Greeting state={state} done={after} />}
      {can(user, "door.act") && <Announcements state={state} done={after} />}
    </div>
  );
}

function Bell({ status, done }: { status: DoorStatus | null; done: () => void }) {
  const a = useAction(done);
  const muted = !!status?.bell_muted;
  const until = status?.bell_muted_until ?? "";
  const quietOn = status?.quiet_enabled ?? null;
  return (
    <Section icon={muted ? "bell-off" : "bell"} title="Klingel"
             extra={muted ? <span class="chip warn">stumm{until ? ` bis ${dayHm(until)}` : ""}</span> : undefined}>
      {muted ? (
        <div class="row gap">
          <span>Stumm{until ? ` bis ${dayHm(until)}` : " bis du ausschaltest"}. Aufs Handy kommt die Meldung trotzdem.</span>
          <button disabled={a.busy} onClick={() => a.run(() => api.bell({ off: true }))}>Klingel wieder an</button>
        </div>
      ) : (
        <>
          <p class="meta">Stumm schalten: im Haus klingelt nichts, aufs Handy kommt die Meldung trotzdem.</p>
          <div class="row gap">
            {MUTE_FOR.map((m) => <button class="chip" disabled={a.busy} onClick={() => a.run(() => api.bell(m.body))}>{m.label}</button>)}
          </div>
        </>
      )}
      <div class="row gap quiet">
        <label class="switch">
          <input type="checkbox" checked={!!quietOn} disabled={a.busy || quietOn === null}
                 onChange={(e) => a.run(() => api.quietHours({ enabled: e.currentTarget.checked }))} />
          <span>Ruhezeit</span>
        </label>
        <span class="grow" />
        <input type="time" class="time" value={status?.quiet_start ?? ""} disabled={a.busy}
               onChange={(e) => e.currentTarget.value && a.run(() => api.quietHours({ start: e.currentTarget.value }))} />
        <span>–</span>
        <input type="time" class="time" value={status?.quiet_end ?? ""} disabled={a.busy}
               onChange={(e) => e.currentTarget.value && a.run(() => api.quietHours({ end: e.currentTarget.value }))} />
      </div>
      {a.msg && <p class="meta">{a.msg}</p>}
    </Section>
  );
}

function Picture({ state, done }: { state: DoorActionsState; done: () => void }) {
  const a = useAction(done);
  const file = useRef<HTMLInputElement>(null);
  const [version, setVersion] = useState(Date.now());
  const [crop, setCrop] = useState<File | null>(null);
  const choose = (f: File | undefined) => {
    if (file.current) file.current.value = "";
    if (f) setCrop(f);
  };
  const send = async (blob: Blob) => {
    setCrop(null);
    await a.run(async () => {
      await api.putPicture(blob);
      setVersion(Date.now());
    }, "Das Bild ist an der Tür.");
  };
  if (crop) {
    return (
      <Section icon="image" title="Bild an der Tür">
        <Cropper file={crop} onDone={send} onCancel={() => setCrop(null)} />
      </Section>
    );
  }
  return (
    <Section icon="image" title="Bild an der Tür">
      <div class="row gap picture">
        {state.picture
          ? <img src={`/api/v1/door/picture?v=${version}`} alt="Bild an der Tür" />
          : <span class="placeholder"><Icon name="image" /></span>}
        <div>
          <p class="meta">Grau, wie es die Tür zeigt. Du schneidest es aufs Feld der Tür zu. Bleibt, bis du es entfernst.</p>
          <div class="row gap">
            <button disabled={a.busy} onClick={() => file.current?.click()}>{a.busy ? "Lade hoch …" : "Foto wählen"}</button>
            {state.picture && (
              <button class="link danger" disabled={a.busy} onClick={() => a.run(() => api.deletePicture(), "Entfernt.")}>Entfernen</button>
            )}
          </div>
        </div>
      </div>
      <input ref={file} type="file" accept="image/*" hidden onChange={(e) => choose(e.currentTarget.files?.[0])} />
      {a.msg && <p class="meta">{a.msg}</p>}
    </Section>
  );
}

function Greeting({ state, done }: { state: DoorActionsState; done: () => void }) {
  const g = state.greeting;
  const a = useAction(done);
  const [text, setText] = useState(g.text);
  const [always, setAlways] = useState(!g.start && !g.end);
  const [start, setStart] = useState(toLocalInput(g.start));
  const [end, setEnd] = useState(toLocalInput(g.end));
  const [recording, setRecording] = useState(false);
  const [version, setVersion] = useState(Date.now());
  const rec = useRef(new Recorder());

  const save = () => a.run(() => api.putGreeting(always ? { text, always: true }
    : { text, start: fromLocalInput(start) || undefined, end: fromLocalInput(end) || undefined }), "Gespeichert.");
  const record = async () => {
    if (recording) return rec.current.stop();
    a.setMsg("");
    try {
      await rec.current.start((blob) => {
        setRecording(false);
        a.run(async () => {
          await api.putGreetingAudio(blob);
          setVersion(Date.now());
        }, "Ton gespeichert.");
      });
      setRecording(true);
    } catch {
      a.setMsg("Kein Zugriff aufs Mikrofon.");
    }
  };
  const label = g.state === "active" ? "läuft" : g.state === "scheduled" ? "geplant" : "aus";
  return (
    <Section icon="hand" title="Begrüßung" extra={<span class={`chip ${g.state === "active" ? "ok" : ""}`}>{label}</span>}>
      <label class="switch">
        <input type="checkbox" checked={g.enabled} disabled={a.busy}
               onChange={(e) => a.run(() => api.putGreeting({ enabled: e.currentTarget.checked }))} />
        <span>Für jeden, der sich nähert, einmal pro Besuch</span>
      </label>
      <input value={text} maxLength={120} placeholder="Text an der Tür (bis 120 Zeichen)" onInput={(e) => setText(e.currentTarget.value)} />
      <div class="row gap">
        {Recorder.supported() && (
          <button class={recording ? "primary" : ""} disabled={a.busy} onClick={record}>
            <Icon name="mic" />{recording ? `Stopp (höchstens ${RECORD_MAX_S} s)` : g.audio ? "Neu aufnehmen" : "Ton aufnehmen"}
          </button>
        )}
        {g.audio && !recording && (
          <>
            <audio controls preload="none" src={`/api/v1/door/greeting/audio?v=${version}`} />
            <button class="link danger" disabled={a.busy} onClick={() => a.run(() => api.deleteGreetingAudio(), "Ton entfernt.")}>
              Ton entfernen
            </button>
          </>
        )}
      </div>
      <label class="switch">
        <input type="checkbox" checked={always} onChange={(e) => setAlways(e.currentTarget.checked)} />
        <span>Immer (ohne Zeitraum)</span>
      </label>
      {!always && (
        <div class="row gap">
          <label>von<input type="datetime-local" value={start} onInput={(e) => setStart(e.currentTarget.value)} /></label>
          <label>bis<input type="datetime-local" value={end} onInput={(e) => setEnd(e.currentTarget.value)} /></label>
        </div>
      )}
      <div class="row gap">
        <button class="primary" disabled={a.busy} onClick={save}>Speichern</button>
        <span class="meta">Ohne Ton liest die Tür den Text in deiner Stimme vor (Haus → Meine Stimme), sonst steht er nur da.</span>
      </div>
      {a.msg && <p class="meta">{a.msg}</p>}
    </Section>
  );
}
