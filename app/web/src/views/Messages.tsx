// Door messages (A10, A15): newest first, filter "Alle / Neu / Für mich", play through the app. "Heard" is kept in Home
// Assistant per person; forward by hand (A37); delete for good (A38, only where the server says so).
import { useEffect, useState } from "preact/hooks";
import { api, can, type DoorMessage, type User } from "../api";
import { duration, splitSpeaker, when } from "../format";
import { share, shareFile, shareText } from "../share";
import { AudioPlayer } from "./AudioPlayer";
import { Icon } from "./Icon";

type Filter = "alle" | "neu" | "mich";

function speakerAndWords(m: DoorMessage): { speaker: string; words: string } {
  return m.speaker ? { speaker: m.speaker, words: m.text } : splitSpeaker(m.text);
}

export function Messages({ user }: { user: User }) {
  const [messages, setMessages] = useState<DoorMessage[] | null>(null);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState<Filter>("alle");
  const [confirming, setConfirming] = useState("");
  const [busy, setBusy] = useState("");
  const [ready, setReady] = useState<{ id: string; file: File; text: string } | null>(null);
  const [notice, setNotice] = useState<{ id: string; text: string } | null>(null);

  const load = () => {
    setError("");
    api.doorMessages().then(setMessages).catch((e) => setError(e.message));
  };
  useEffect(() => {
    load();
    const again = () => document.visibilityState === "visible" && load();
    document.addEventListener("visibilitychange", again);
    return () => document.removeEventListener("visibilitychange", again);
  }, []);

  const update = (id: string, change: (m: DoorMessage) => DoorMessage | null) =>
    setMessages((list) => (list ?? []).flatMap((m) => (m.id === id ? [change(m)].filter((x): x is DoorMessage => !!x) : [m])));

  const markHeard = (m: DoorMessage) => {
    if (m.heard) return;
    update(m.id, (x) => ({ ...x, heard: true }));
    api.messageHeard(m.id).catch(() => {
      // only the "new" dot; the next reload shows the truth
    });
  };

  const done = (id: string, result: string) => {
    setReady(null);
    if (result === "saved") setNotice({ id, text: "MP3 gespeichert, Text kopiert." });
  };

  const forward = async (m: DoorMessage) => {
    setNotice(null);
    setBusy(m.id);
    try {
      const { speaker, words } = speakerAndWords(m);
      const text = shareText(m, speaker, words);
      const file = await shareFile(m);
      const result = await share(file, text);
      if (result === "needs-tap") setReady({ id: m.id, file, text });
      else done(m.id, result);
    } catch (e) {
      setNotice({ id: m.id, text: (e as Error).message });
    } finally {
      setBusy("");
    }
  };

  const forwardReady = async () => {
    if (!ready) return;
    try {
      done(ready.id, await share(ready.file, ready.text));
    } catch (e) {
      setNotice({ id: ready.id, text: (e as Error).message });
      setReady(null);
    }
  };

  const remove = async (m: DoorMessage) => {
    setBusy(m.id);
    try {
      await api.deleteMessage(m.id);
      update(m.id, () => null);
    } catch (e) {
      setNotice({ id: m.id, text: (e as Error).message });
    } finally {
      setBusy("");
      setConfirming("");
    }
  };

  const mine = (m: DoorMessage) => m.recipient.trim().toLowerCase() === user.name.trim().toLowerCase();
  const shown = (messages ?? []).filter((m) => filter === "alle" || (filter === "neu" ? !m.heard : mine(m)));
  const newCount = (messages ?? []).filter((m) => !m.heard).length;

  return (
    <div>
      <div class="filters">
        {(["alle", "neu", "mich"] as Filter[]).map((f) => (
          <button class={`chip ${filter === f ? "selected" : ""}`} onClick={() => setFilter(f)}>
            {f === "alle" ? "Alle" : f === "neu" ? `Neu${newCount ? ` (${newCount})` : ""}` : "Für mich"}
          </button>
        ))}
        <span class="grow" />
        <button class="chip" onClick={load} aria-label="Neu laden">↻</button>
      </div>
      {error && <p class="error pad">{error}</p>}
      {messages === null && !error && <p class="muted pad">Lade …</p>}
      {messages !== null && shown.length === 0 && (
        <p class="muted pad">{filter === "alle" ? "Noch keine Nachrichten an der Tür." : "Keine Nachrichten in dieser Auswahl."}</p>
      )}
      <ul class="list">
        {shown.map((m) => {
          const { speaker, words } = speakerAndWords(m);
          const forOther = m.recipient && !mine(m);
          const others = m.heard_by.filter((n) => n.trim().toLowerCase() !== user.name.trim().toLowerCase());
          return (
            <li class="card" key={m.id}>
              <div class="row">
                {!m.heard && <span class="dot" aria-label="neu" />}
                <strong class="speaker">{speaker || "Besucher"}</strong>
                <span class="grow" />
                {m.recipient
                  ? <span class={`badge ${forOther ? "warn" : "accent"}`}>für {m.recipient}</span>
                  : <span class="badge">an alle</span>}
              </div>
              {words ? <p class="said">„{words}“</p> : <p class="said muted">Kein Text erkannt.</p>}
              {m.audio
                ? <AudioPlayer src={m.audio} seconds={m.seconds} onPlay={() => markHeard(m)} />
                : <p class="meta">Der Ton ist nicht mehr da.</p>}
              <p class="meta">
                {when(m.time)}
                {m.seconds != null && ` · ${duration(m.seconds)}`}
                {forOther && can(user, "messages.all") && ` · sehen nur ${m.recipient} und du`}
                {others.length > 0 && ` · gehört von ${others.join(", ")}`}
              </p>
              <div class="row actions">
                {ready?.id === m.id
                  ? <button class="primary" onClick={forwardReady}><Icon name="share" />Jetzt teilen</button>
                  : <button class="link" onClick={() => forward(m)} disabled={!m.audio || busy === m.id}>
                      <Icon name="share" />{busy === m.id && confirming !== m.id ? "Hole Ton …" : "Teilen"}
                    </button>}
                <span class="grow" />
                {m.may_delete && (confirming === m.id
                  ? <>
                      <span class="meta">Ton und Text endgültig löschen?</span>
                      <button class="link danger" onClick={() => remove(m)} disabled={busy === m.id}>Löschen</button>
                      <button class="link" onClick={() => setConfirming("")}>Nein</button>
                    </>
                  : <button class="link danger" onClick={() => setConfirming(m.id)}><Icon name="trash" />Löschen</button>)}
              </div>
              {notice?.id === m.id && <p class="meta">{notice.text}</p>}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
