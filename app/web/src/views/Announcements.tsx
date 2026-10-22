// Ansagen (sprachausgabe S10–S14): what the door says after a ring, in the voice of whoever saved the sentences, as far as
// the slider allows. The residents write the sentences (with suggestions); aikos only picks which one fits now.
import { useRef, useState } from "preact/hooks";
import { api, type DoorAnnouncements, type DoorActionsState } from "../api";
import { dayHm, Section, useAction } from "./DoorParts";
import { Icon } from "./Icon";

const LEVELS = [
  "Nichts. Nach dem Klingeln sagt die Tür nichts.",
  "Dass gerade niemand kommen kann oder niemand zu Hause ist, und wohin ein Paket soll.",
  "Wie Stufe 1 (dass ihr im Garten seid, kommt später).",
  "Wie Stufe 1 (wann ihr zurück seid, kommt später).",
  "Auch, wo ihr gerade seid: nur wer selbst zugestimmt hat, nur Orte, die unten einen Namen haben.",
];

type Key = "parcel" | "away" | "away_places" | "quiet";
const SENTENCES: { key: Key; title: string; when: string; suggestions: string[]; from?: number }[] = [
  { key: "parcel", title: "Paket erwartet", when: "Heute kommt laut Zustell-Mail ein Paket. Schon, wenn jemand an die Tür kommt.",
    suggestions: ["Bitte legen Sie das Paket vor die Tür. Danke!", "Bitte stellen Sie das Paket vor der Tür ab."] },
  { key: "away", title: "Alle unterwegs", when: "Niemand von euch ist zu Hause.",
    suggestions: ["Wir sind gerade nicht zu Hause.", "Gerade ist niemand da. Sie können gern eine Nachricht hinterlassen."] },
  { key: "away_places", title: "Alle unterwegs, mit Ort", from: 4,
    when: "Ab Stufe 4 statt des Satzes darüber. {wo} wird z. B. zu „Alex ist beim Bäcker und Kim ist im Büro“.",
    suggestions: ["Wir sind gerade unterwegs: {wo}.", "Gerade ist niemand zu Hause. {wo}."] },
  { key: "quiet", title: "Klingel stumm oder Ruhezeit", when: "Jemand ist da, möchte aber gerade nicht gestört werden.",
    suggestions: ["Wir können gerade nicht an die Tür kommen.", "Bitte nicht klingeln, wir melden uns später."] },
];
const NOW: Record<string, string> = { parcel: "Paket erwartet", away: "alle unterwegs", quiet: "stumm / Ruhezeit" };

export function Announcements({ state, done }: { state: DoorActionsState; done: () => void }) {
  const an = state.announcements;
  if (!an) {
    return (
      <Section icon="speaker" title="Ansagen">
        <p class="meta">Dafür braucht Home Assistant die aikos-Integration ab 0.11.0.</p>
      </Section>
    );
  }
  return <Editor an={an} done={done} />;
}

function Editor({ an, done }: { an: DoorAnnouncements; done: () => void }) {
  const a = useAction(done);
  const [texts, setTexts] = useState<Record<Key, string>>({
    parcel: an.parcel, away: an.away, away_places: an.away_places, quiet: an.quiet });
  const [places, setPlaces] = useState<Record<string, string>>(an.places);
  const [level, setLevel] = useState(an.disclosure);
  const player = useRef<HTMLAudioElement>(null);

  const changed = SENTENCES.some((s) => texts[s.key] !== an[s.key])
    || an.zones.some((z) => (places[z.id] ?? "") !== (an.places[z.id] ?? ""));
  const badWhere = !!texts.away_places && !texts.away_places.includes("{wo}");
  const save = () => a.run(() => api.putAnnouncements({ ...texts, places }), an.voice || level > 0 ? "Gespeichert. Die Sätze werden jetzt vorbereitet." : "Gespeichert.");
  const setDisclosure = (v: number) => {
    setLevel(v);
    a.run(() => api.putAnnouncements({ disclosure: v }), `Stufe ${v} gilt.`);
  };
  const listen = (text: string) => a.run(async () => {
    const url = URL.createObjectURL(await api.myVoiceSample(text.replace("{wo}", "Alex ist beim Bäcker")));
    player.current!.src = url;
    await player.current!.play();
  }, "");

  return (
    <Section icon="speaker" title="Ansagen" extra={<span class={`chip ${level > 0 ? "ok" : ""}`}>{level > 0 ? `Stufe ${level}` : "aus"}</span>}>
      <p class="meta">Nach dem Klingeln sagt die Tür einen eurer Sätze, wenn er passt. Welcher, entscheidet aikos fest nach der Lage, nie ein Modell.</p>
      <label class="zoom">Was die Tür verraten darf
        <input type="range" min={0} max={4} step={1} value={level} disabled={a.busy}
               onChange={(e) => setDisclosure(Number(e.currentTarget.value))} />
      </label>
      <p class="meta"><b>Stufe {level}:</b> {LEVELS[level]}</p>

      {SENTENCES.map((s) => (
        <div class={`announce ${s.from && level < s.from ? "dim" : ""}`}>
          <b>{s.title}</b>
          <span class="meta">{s.when}</span>
          <div class="row">
            <input value={texts[s.key]} maxLength={200} placeholder="leer = nichts sagen"
                   onInput={(e) => setTexts({ ...texts, [s.key]: e.currentTarget.value })} />
            <button disabled={a.busy || !texts[s.key]} title="In deiner Stimme anhören" onClick={() => listen(texts[s.key])}>
              <Icon name="play" />
            </button>
          </div>
          <div class="row gap">
            {s.suggestions.map((q) => <button class="chip" onClick={() => setTexts({ ...texts, [s.key]: q })}>{q}</button>)}
          </div>
        </div>
      ))}
      {badWhere && <p class="error">Im Satz mit Ort fehlt {"{wo}"}.</p>}

      {level >= 4 && (
        <div class="announce">
          <b>Orte, die die Tür nennen darf</b>
          <span class="meta">Wie die Tür den Ort sagt, z. B. „beim Bäcker“. Leer = wird nie genannt.</span>
          {an.zones.length === 0 && <span class="meta">In Home Assistant gibt es noch keine Zonen.</span>}
          {an.zones.map((z) => (
            <label class="row">
              <span class="grow">{z.name}</span>
              <input value={places[z.id] ?? ""} maxLength={40} placeholder="nicht nennen"
                     onInput={(e) => setPlaces({ ...places, [z.id]: e.currentTarget.value })} />
            </label>
          ))}
          <span class="meta">Genannt wird nur, wer selbst zugestimmt hat:{" "}
            {an.residents.map((r) => `${r.name} ${r.named ? "✓" : "–"}`).join(", ") || "keine Bewohner eingestellt"}.
          </span>
          {an.me.resident && (
            <label class="switch">
              <input type="checkbox" checked={an.me.named} disabled={a.busy}
                     onChange={(e) => a.run(() => api.putAnnouncements({ name_me: e.currentTarget.checked }))} />
              <span>Die Tür darf sagen, wo ich gerade bin</span>
            </label>
          )}
        </div>
      )}

      <div class="row gap">
        <button class="primary" disabled={a.busy || !changed || badWhere} onClick={save}>Speichern</button>
        <span class="meta">
          {an.voice ? "Gesprochen in der Stimme dessen, der zuletzt gespeichert hat."
            : "Noch keine Stimme: nimm unter Haus → Meine Stimme deine auf und speichere dann. Bis dahin sagt die Tür nichts."}
        </span>
      </div>
      <p class="meta">
        {an.now !== "none" && an.now_text ? <>Jetzt ({an.now.split("+").map((k) => NOW[k] ?? k).join(" + ")}) würde die Tür sagen: „{an.now_text}“</>
          : "Jetzt würde die Tür nach dem Klingeln nichts sagen."}
        {an.last.text && <> · Zuletzt {dayHm(an.last.at ?? "")}: „{an.last.text}“</>}
      </p>
      <audio ref={player} hidden />
      {a.msg && <p class="meta">{a.msg}</p>}
    </Section>
  );
}
