// Meine Stimme (A43–A45, S9): record your own voice so the door reads your notes in it. The recording goes to the
// house's voice service only; only your own notes and greetings are read in it; delete it any time.
import { useEffect, useRef, useState } from "preact/hooks";
import { api, type MyVoice as MyVoiceState } from "../api";
import { Recorder } from "../media";
import { Icon } from "./Icon";

const MAX_S = 45;

export function MyVoice() {
  const [state, setState] = useState<MyVoiceState | null>(null);
  const [recording, setRecording] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const [busy, setBusy] = useState("");
  const [msg, setMsg] = useState("");
  const [confirm, setConfirm] = useState(false);
  const rec = useRef(new Recorder());
  const timer = useRef(0);
  const player = useRef<HTMLAudioElement>(null);

  const load = () => api.myVoice().then(setState).catch((e) => setMsg(e.message));
  useEffect(() => {
    load();
    return () => clearInterval(timer.current);
  }, []);

  const record = async () => {
    if (recording) return rec.current.stop();
    setMsg("");
    try {
      await rec.current.start(async (blob) => {
        clearInterval(timer.current);
        setRecording(false);
        setBusy("Speichere deine Stimme …");
        try {
          const v = await api.putMyVoice(blob);
          setMsg(`Deine Stimme ist gespeichert (${Math.round(v.seconds)} s). Hör dir die Probe an.`);
          load();
        } catch (e) {
          setMsg((e as Error).message);
        } finally {
          setBusy("");
        }
      }, MAX_S);
      setSeconds(0);
      setRecording(true);
      timer.current = window.setInterval(() => setSeconds((s) => s + 1), 1000);
    } catch {
      setMsg("Kein Zugriff aufs Mikrofon.");
    }
  };

  const sample = async () => {
    setBusy("Die Probe wird gesprochen (ein paar Sekunden) …");
    setMsg("");
    try {
      const url = URL.createObjectURL(await api.myVoiceSample());
      const a = player.current!;
      a.src = url;
      await a.play();
    } catch (e) {
      setMsg((e as Error).message);
    } finally {
      setBusy("");
    }
  };

  const remove = async () => {
    setConfirm(false);
    setBusy("Lösche …");
    try {
      await api.deleteMyVoice();
      setMsg("Deine Stimme ist gelöscht.");
      load();
    } catch (e) {
      setMsg((e as Error).message);
    } finally {
      setBusy("");
    }
  };

  if (!state) return null;
  return (
    <section class="pad myvoice">
      <h2>Meine Stimme</h2>
      {!state.available ? (
        <p class="meta">Der Sprachdienst des Hauses ist noch nicht eingerichtet.</p>
      ) : (
        <>
          <p class="meta">
            Die Tür liest deine Nachrichten in deiner eigenen Stimme vor. Deine Aufnahme geht nur an den Sprachdienst im Haus,
            nie ins Internet. Vorgelesen werden nur deine eigenen Nachrichten. Du kannst sie jederzeit löschen.
          </p>
          {state.voice && (
            <div class="row gap">
              <span>Eingerichtet ({Math.round(state.voice.seconds ?? 0)} s Aufnahme)</span>
              <button disabled={!!busy || recording} onClick={sample}><Icon name="play" />Probe anhören</button>
              {confirm
                ? <>
                    <span class="meta">Stimme endgültig löschen?</span>
                    <button class="link danger" onClick={remove}>Löschen</button>
                    <button class="link" onClick={() => setConfirm(false)}>Nein</button>
                  </>
                : <button class="link danger" disabled={!!busy} onClick={() => setConfirm(true)}>Stimme löschen</button>}
            </div>
          )}
          <p class="meta">{state.voice ? "Neu aufnehmen:" : "So geht's:"} ruhiger Raum, Handy etwa 20 cm vor dem Mund, diesen Text
            in deiner normalen Sprechweise vorlesen (etwa 25 Sekunden):</p>
          <blockquote class="reading">{state.reading}</blockquote>
          <div class="row gap">
            <button class={recording ? "primary" : ""} disabled={!!busy} onClick={record}>
              <Icon name="mic" />{recording ? `Fertig (${seconds} s)` : state.voice ? "Neu aufnehmen" : "Aufnahme starten"}
            </button>
            {recording && seconds < 15 && <span class="meta">Lies weiter, mindestens 15 Sekunden …</span>}
          </div>
        </>
      )}
      {busy && <p class="meta">{busy}</p>}
      {msg && <p class="meta">{msg}</p>}
      <audio ref={player} hidden />
    </section>
  );
}
