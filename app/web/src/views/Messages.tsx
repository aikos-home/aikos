// Door messages (A10, A15): newest first, filter "Alle / Neu / Für mich", play through the app.
import { useEffect, useState } from "preact/hooks";
import { api, can, type DoorMessage, type User } from "../api";
import { duration, splitSpeaker, when } from "../format";
import { AudioPlayer } from "./AudioPlayer";

type Filter = "alle" | "neu" | "mich";
const heardKey = (user: User) => `aikos.heard.${user.id}`;

function loadHeard(user: User): Set<string> {
  try {
    return new Set(JSON.parse(localStorage.getItem(heardKey(user)) ?? "[]"));
  } catch {
    return new Set();
  }
}

function saveHeard(user: User, heard: Set<string>) {
  try {
    localStorage.setItem(heardKey(user), JSON.stringify([...heard].slice(-500)));
  } catch {
    // only a convenience on this device; the register in Home Assistant takes over in step 2
  }
}

export function Messages({ user }: { user: User }) {
  const [messages, setMessages] = useState<DoorMessage[] | null>(null);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState<Filter>("alle");
  const [heard, setHeard] = useState<Set<string>>(() => loadHeard(user));

  const load = () => {
    setError("");
    api.doorMessages().then(setMessages).catch((e) => setError(e.message));
  };
  useEffect(load, []);

  const markHeard = (id: string) => {
    const next = new Set(heard).add(id);
    setHeard(next);
    saveHeard(user, next);
  };

  const mine = (m: DoorMessage) => m.recipient.trim().toLowerCase() === user.name.trim().toLowerCase();
  const shown = (messages ?? []).filter((m) => filter === "alle" || (filter === "neu" ? !heard.has(m.id) : mine(m)));
  const newCount = (messages ?? []).filter((m) => !heard.has(m.id)).length;

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
          const { speaker, words } = splitSpeaker(m.text);
          const forOther = m.recipient && !mine(m);
          return (
            <li class="card" key={m.id}>
              <div class="row">
                {!heard.has(m.id) && <span class="dot" aria-label="neu" />}
                <strong class="speaker">{speaker || "Besucher"}</strong>
                <span class="grow" />
                {m.recipient
                  ? <span class={`badge ${forOther ? "warn" : "accent"}`}>für {m.recipient}</span>
                  : <span class="badge">an alle</span>}
              </div>
              {words ? <p class="said">„{words}“</p> : <p class="said muted">Kein Text erkannt.</p>}
              <AudioPlayer src={m.audio} seconds={m.seconds} onPlay={() => markHeard(m.id)} />
              <p class="meta">
                {when(m.time)}
                {m.seconds != null && ` · ${duration(m.seconds)}`}
                {forOther && can(user, "messages.all") && ` · sehen nur ${m.recipient} und du`}
              </p>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
