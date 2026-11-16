// Gespräch an der Tür as a chat (A47–A49; the owner: "wie so ein Chatlog", "wie bei WhatsApp"): the visit's thread from
// the aikos integration (ring, visitor, house, answers and whether they were read aloud, voice messages, announcements,
// messages), newest at the bottom, and a composer like a messenger's: quick replies, text (read at the door in one's own
// voice) and the microphone. Holding it talks live, as at a room key (the owner, 22.10.: "Live wie RoomKey"): the door
// hears it at once and its chat shows it. Only when nobody is at the door and no call runs, holding records a voice
// message for the next visitor. Anyone may write at any time.
import { useEffect, useRef, useState } from "preact/hooks";
import { api, type DoorActionsState, type DoorCall, type ThreadEntry } from "../api";
import { Recorder } from "../media";
import { DoorTalk, type TalkState } from "../talk";
import { dayHm, hm } from "./DoorParts";
import { Icon } from "./Icon";

const TALK_LABEL: Record<TalkState, string> = {
  connecting: "Verbinde mit der Tür …", listening: "Im Gespräch: du hörst die Tür. Mikrofon halten zum Sprechen.",
  talking: "Die Tür hört dich.", busy: "Aus der App spricht schon jemand.", off: "", error: "Keine Verbindung zur Tür.",
};
const VOICE_MAX_S = 45;      // the door plays at most 50 s of a sound
const VOICE_BITS = 64000;    // 45 s stay well under the app's upload limit, also as AAC on an iPhone
const VOICE_MIN_MS = 700;    // shorter is a tap, not a message

/** Before aikos 0.17.0 there is no thread: the call log's lines stand in for it. */
function entriesOf(call: DoorCall): ThreadEntry[] {
  if (call.thread) return call.thread.entries;
  return call.messages.map((m) => ({ id: m.id, t: "", kind: m.side, who: m.who, text: m.text, spoken: null }));
}

const mmss = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s) % 60).padStart(2, "0")}`;

function Voice({ e }: { e: ThreadEntry }) {
  const [playing, setPlaying] = useState(false);
  const audio = useRef<HTMLAudioElement | null>(null);
  useEffect(() => () => audio.current?.pause(), []);
  const toggle = () => {
    if (!audio.current) {
      audio.current = new Audio(`/api/v1/door/voice/${encodeURIComponent(e.voice ?? "")}`);
      audio.current.onended = () => setPlaying(false);
    }
    if (playing) {
      audio.current.pause();
      setPlaying(false);
    } else {
      audio.current.play().then(() => setPlaying(true), () => setPlaying(false));
    }
  };
  return (
    <span class="chat-voice">
      <button type="button" class="round" aria-label={playing ? "Anhalten" : "Anhören"} onClick={toggle}>
        <Icon name={playing ? "pause" : "play"} />
      </button>
      <span class={`chat-wave ${playing ? "on" : ""}`} />
      <span class="chat-len">{e.seconds ? mmss(Math.max(1, e.seconds)) : ""}</span>
    </span>
  );
}

function Bubble({ e, me }: { e: ThreadEntry; me: string }) {
  const time = e.t ? hm(e.t) : "";
  if (e.kind === "ring" || e.kind === "announce" || e.kind === "message") {
    const text = e.kind === "announce" ? `Die Tür sagte: „${e.text}“` : e.kind === "message" ? `Besucher ${e.text}` : e.text;
    return (
      <li class="chat-event">
        <Icon name={e.kind === "ring" ? "bell" : e.kind === "announce" ? "speaker" : "message"} />
        <span>{text}</span>{time && <span class="chat-time">{time}</span>}
      </li>
    );
  }
  const ours = e.kind !== "door";
  const who = e.kind === "door" ? (e.who || "Besucher") : (e.who && e.who === me ? "Du" : e.who || "Haus");
  const note = e.kind === "waiting" ? "wartet auf den nächsten Besucher"
    : e.kind === "reply" ? (e.spoken === true ? "vorgelesen ✓" : e.spoken === false ? "nur angezeigt" : "wird vorgelesen …")
    : e.kind === "voice" ? (e.spoken === true ? "abgespielt ✓" : e.spoken === false ? "nicht abgespielt" : "wird abgespielt …")
    : e.kind === "room" ? (e.via === "app" ? "live aus der App" : "über den RoomKey") : "";
  return (
    <li class={`chat-msg ${ours ? "ours" : "theirs"} k-${e.kind}`}>
      <span class="chat-who">{who}</span>
      {e.voice ? <Voice e={e} /> : <span class="chat-text">{e.text}</span>}
      <span class="chat-time">{[time, note].filter(Boolean).join(" · ")}</span>
    </li>
  );
}

export function Call({ state, me, here, done }: { state: DoorActionsState; me: string; here: boolean; done: () => void }) {
  const [call, setCall] = useState<DoorCall | null>(null);
  const [talkState, setTalkState] = useState<TalkState>("off");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [recording, setRecording] = useState(false);
  const [recS, setRecS] = useState(0);
  const talk = useRef<DoorTalk | null>(null);
  const log = useRef<HTMLUListElement>(null);
  const draft = useRef<number>();
  const rec = useRef<Recorder | null>(null);
  const held = useRef(false);
  const keep = useRef(false);
  const since = useRef(0);

  const load = () => api.doorCall().then(setCall).catch(() => {});
  useEffect(() => {
    load();
    const t = setInterval(load, 1500);
    return () => {
      clearInterval(t);
      talk.current?.stop();
      keep.current = false;
      rec.current?.stop();
    };
  }, []);
  useEffect(() => {   // the recording's running time, like a messenger
    if (!recording) return;
    const t = setInterval(() => setRecS((Date.now() - since.current) / 1000), 250);
    return () => clearInterval(t);
  }, [recording]);

  const entries = call ? entriesOf(call) : [];
  useEffect(() => {   // the newest line in view, like a messenger
    if (log.current) log.current.scrollTop = log.current.scrollHeight;
  }, [entries.length, entries[entries.length - 1]?.spoken]);

  if (!call) return null;
  const joined = talkState === "listening" || talkState === "talking";
  const canTalk = call.talk && DoorTalk.supported();

  const send = async (job: () => Promise<unknown>) => {
    setBusy(true);
    setMsg("");
    try {
      await job();
      done();
      load();
    } catch (e) {
      setMsg((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const say = (message: string) => send(async () => {
    await api.say(message);
    setText("");
  });
  const typed = (value: string) => {   // its speech is made while typing, so it plays at once when sent
    setText(value);
    window.clearTimeout(draft.current);
    const m = value.trim();
    if (m.length >= 3) draft.current = window.setTimeout(() => api.sayDraft(m).catch(() => {}), 900);
  };

  // live, as at a room key: the first press joins the call (the phone asks for the microphone once), and the talking
  // starts as soon as the door has the app in the call; letting go ends the sentence, the call stays until hung up
  const join = async () => {
    talk.current = new DoorTalk((s, detail) => {
      setTalkState(s);
      if (detail) setMsg(detail);
      if (s === "listening" && held.current) talk.current?.hold(true);
      if (s === "off" || s === "error" || s === "busy") talk.current = null;
    });
    try {
      await talk.current.start();
    } catch {
      talk.current = null;
      setTalkState("error");
      setMsg("Kein Zugriff aufs Mikrofon.");
    }
  };
  const leave = () => {
    talk.current?.stop();
    talk.current = null;
    setTalkState("off");
  };

  // a voice message (nobody at the door, no call): let go to send it, slide off the button to throw it away
  const recorded = (blob: Blob) => {
    setRecording(false);
    rec.current = null;
    const seconds = (Date.now() - since.current) / 1000;
    if (!keep.current || !blob.size) return;
    send(() => api.sayAudio(blob, Math.round(seconds * 10) / 10));
  };
  const record = async () => {
    keep.current = true;
    const r = new Recorder();
    try {
      await r.start(recorded, VOICE_MAX_S, VOICE_BITS);
    } catch {
      setMsg("Kein Zugriff aufs Mikrofon.");
      return;
    }
    since.current = Date.now();
    rec.current = r;
    if (!held.current) {   // let go while the phone asked for the microphone: nothing to send yet
      keep.current = false;
      r.stop();
      setMsg("Zum Aufnehmen gedrückt halten.");
      return;
    }
    setRecS(0);
    setRecording(true);
  };

  const live = canTalk && (joined || call.active || here);
  const press = async (e: PointerEvent) => {
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    held.current = true;
    setMsg("");
    if (!live) return record();
    if (talk.current) talk.current.hold(true);
    else await join();
  };
  const release = (e: PointerEvent, cancel = false) => {
    held.current = false;
    if (talk.current) {
      talk.current.hold(false);
      return;
    }
    if (!rec.current) return;
    const b = (e.currentTarget as HTMLElement).getBoundingClientRect();
    const near = e.clientX > b.left - 60 && e.clientX < b.right + 60 && e.clientY > b.top - 80 && e.clientY < b.bottom + 60;
    const long = Date.now() - since.current >= VOICE_MIN_MS;
    keep.current = !cancel && near && long;
    if (!long) setMsg("Zum Aufnehmen gedrückt halten.");
    else if (!keep.current) setMsg("Sprachnachricht verworfen.");
    rec.current.stop();
  };

  const first = entries.find((e) => e.t);
  const status = call.active ? <span class="chip ok">Gespräch läuft</span>
    : first ? <span class="chip">{`Besuch ${dayHm(first.t)}`}</span> : undefined;
  const mic = !text.trim() && (live || Recorder.supported());
  const talking = talkState === "talking";
  return (
    <section class="chat">
      <header class="chat-head"><Icon name="door" /><b>Gespräch an der Tür</b><span class="grow" />{status}</header>
      <ul class="chat-log" ref={log}>
        {entries.length === 0 && (
          <li class="chat-empty">Noch nichts an der Tür. Du kannst trotzdem schreiben oder eine Sprachnachricht schicken:
            sie wartet auf den nächsten Besucher.</li>
        )}
        {entries.map((e, i) => <Bubble key={e.id || i} e={e} me={me} />)}
      </ul>
      {state.note && (
        <p class="chat-pinned">
          <span>Wartet seit {hm(state.note.since)}: {state.note.message.startsWith("Sprachnachricht") ? "deine Sprachnachricht"
            : `„${state.note.message}“`}</span>
          <button class="link danger" disabled={busy} onClick={() => send(() => api.cancelSay())}>Zurücknehmen</button>
        </p>
      )}
      {joined && (
        <p class="chat-live-bar">
          <span class="dot" /><span>{TALK_LABEL[talkState]}</span>
          <button class="link danger" onClick={leave}>Auflegen</button>
        </p>
      )}
      {!joined && canTalk && call.active && talkState !== "connecting" && (
        <button class="link chat-listen" onClick={join}><Icon name="speaker" />Mithören</button>
      )}
      <div class="chat-quick">
        {(state.quick ?? []).map((q) => <button class="chip" disabled={busy} onClick={() => say(q)}>{q.replace(/\.$/, "")}</button>)}
      </div>
      <form class="chat-compose" onSubmit={(e) => { e.preventDefault(); if (text.trim()) say(text); }}>
        {recording ? (
          <div class="chat-rec"><span class="dot" />{mmss(recS)}<span class="meta">Loslassen zum Senden · wegziehen verwirft</span></div>
        ) : talking || (held.current && talkState === "connecting") ? (
          <div class="chat-rec"><span class="dot" />{talking ? "Live: die Tür hört dich" : "Verbinde mit der Tür …"}</div>
        ) : (
          <input value={text} maxLength={400} placeholder="Nachricht an die Tür …" onInput={(e) => typed(e.currentTarget.value)} />
        )}
        {mic ? (
          <button type="button" class={`primary round mic ${recording || talking ? "on" : ""}`}
                  aria-label={live ? "Halten zum Sprechen" : "Halten für Sprachnachricht"}
                  disabled={busy} onPointerDown={press} onPointerUp={(e) => release(e)}
                  onPointerCancel={(e) => release(e, true)} onContextMenu={(e) => e.preventDefault()}>
            <Icon name="mic" />
          </button>
        ) : (
          <button class="primary round" aria-label="Senden" disabled={busy || !text.trim()}><Icon name="send" /></button>
        )}
      </form>
      {msg ? <p class="meta">{msg}</p>
        : !joined && <p class="meta">{live ? "Mikrofon halten: live an die Tür, wie am RoomKey."
          : "Niemand an der Tür: Mikrofon halten nimmt eine Sprachnachricht für den nächsten Besucher auf."}</p>}
    </section>
  );
}
