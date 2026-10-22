// Gespräch (A47, A48): what is said at the door, live, and answering it: a quick reply or text (read in one's own voice)
// or live, holding the button (as at a room key). The push on every ring opens the door page here.
import { useEffect, useRef, useState } from "preact/hooks";
import { api, type DoorActionsState, type DoorCall } from "../api";
import { DoorTalk, type TalkState } from "../talk";
import { hm, Section, useAction } from "./DoorParts";
import { Icon } from "./Icon";

const RECENT_MS = 5 * 60_000;
const TALK_LABEL: Record<TalkState, string> = {
  connecting: "Verbinde …", listening: "Du hörst die Tür", talking: "Die Tür hört dich", busy: "Spricht schon jemand aus der App",
  off: "", error: "Keine Verbindung zur Tür",
};

export function Call({ state, done }: { state: DoorActionsState; done: () => void }) {
  const [call, setCall] = useState<DoorCall | null>(null);
  const [talkState, setTalkState] = useState<TalkState>("off");
  const [text, setText] = useState("");
  const talk = useRef<DoorTalk | null>(null);
  const a = useAction(done);

  useEffect(() => {
    let stop = false;
    const load = () => api.doorCall().then((c) => !stop && setCall(c)).catch(() => {});
    load();
    const t = setInterval(load, 1500);
    return () => {
      stop = true;
      clearInterval(t);
      talk.current?.stop();
    };
  }, []);

  if (!call) return null;
  const rang = call.ring ? new Date(call.ring).getTime() : 0;
  const recent = call.active || (rang && Date.now() - rang < RECENT_MS);
  const live = talkState === "listening" || talkState === "talking";

  const join = async () => {
    try {
      talk.current = new DoorTalk((s, detail) => {
        setTalkState(s);
        if (detail) a.setMsg(detail);
      });
      await talk.current.start();
    } catch {
      setTalkState("error");
      a.setMsg("Kein Zugriff aufs Mikrofon.");
    }
  };
  const leave = () => {
    talk.current?.stop();
    talk.current = null;
    setTalkState("off");
  };
  const say = (message: string) => a.run(async () => {
    const r = await api.say(message);
    setText("");
    return r.delivered === "now" ? "An der Tür angezeigt." : "Wartet auf den nächsten Besucher.";
  });

  const chip = call.active ? <span class="chip ok">läuft</span>
    : rang && recent ? <span class="chip warn">geklingelt {hm(call.ring)}</span> : undefined;
  return (
    <Section icon="door" title="Gespräch" extra={chip}>
      {!recent && !live && <p class="meta">Gerade kein Gespräch.{call.ring && ` Zuletzt geklingelt ${hm(call.ring)}.`}</p>}
      {call.messages.length > 0 && (recent || live) && (
        <ul class="transcript">
          {call.messages.map((m) => (
            <li class={m.side}>
              <span class="who">{m.side === "door" ? (m.who || "Tür") : (m.who || "Haus")}</span>
              <span>{m.text}{m.tr && <em class="meta"> ({m.tr})</em>}</span>
            </li>
          ))}
        </ul>
      )}
      {(recent || live) && (
        <>
          <div class="row gap">
            {(state.quick ?? []).map((q) => <button class="chip" disabled={a.busy} onClick={() => say(q)}>{q.replace(/\.$/, "")}</button>)}
          </div>
          <form class="row" onSubmit={(e) => { e.preventDefault(); if (text.trim()) say(text); }}>
            <input value={text} maxLength={400} placeholder="Antwort als Text" onInput={(e) => setText(e.currentTarget.value)} />
            <button class="primary" disabled={a.busy || !text.trim()}>Senden</button>
          </form>
        </>
      )}
      {!call.talk ? <p class="meta">Live sprechen ist auf diesem Server noch nicht eingerichtet.</p>
        : !DoorTalk.supported() ? <p class="meta">Dieser Browser kann nicht live sprechen.</p>
        : !live ? (
          <button disabled={talkState === "connecting"} onClick={join}><Icon name="mic" />Live dabei sein</button>
        ) : (
          <div class="talk">
            <button class={`hold ${talkState === "talking" ? "on" : ""}`}
                    onPointerDown={(e) => { (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId); talk.current?.hold(true); }}
                    onPointerUp={() => talk.current?.hold(false)} onPointerCancel={() => talk.current?.hold(false)}
                    onContextMenu={(e) => e.preventDefault()}>
              <Icon name="mic" />{talkState === "talking" ? "Sprich jetzt" : "Halten zum Sprechen"}
            </button>
            <span class="meta">{TALK_LABEL[talkState]}</span>
            <button class="link danger" onClick={leave}>Auflegen</button>
          </div>
        )}
      {talkState === "busy" && <p class="meta">{TALK_LABEL.busy}.</p>}
      {a.msg && <p class="meta">{a.msg}</p>}
    </Section>
  );
}
