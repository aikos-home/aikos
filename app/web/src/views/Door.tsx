// Door actions. Step 1 shows what comes; the actions arrive with step 3 (feature file aikos-app §2.9).
import { can, type User } from "../api";
import { Icon } from "./Icon";

const COMING = [
  { icon: "mic", title: "Sprechen", text: "Nach draußen sprechen, solange du drückst. Antworten auf Nachrichten nur, solange die Person noch da ist." },
  { icon: "text", title: "Text an die Tür", text: "Wird an der Tür vorgelesen und angezeigt." },
  { icon: "image", title: "Bild an die Tür", text: "Ein Foto vom Handy auf dem Türbildschirm." },
  { icon: "hand", title: "Begrüßung", text: "Text oder Ton für jeden, der kommt, mit Zeitraum von–bis." },
  { icon: "bell-off", title: "Stumm und Ruhezeit", text: "Klingel stumm schalten, Ruhezeiten festlegen." },
];

export function Door({ user }: { user: User }) {
  if (!can(user, "door.act")) return <p class="muted pad">Für dich gibt es hier noch nichts.</p>;
  return (
    <div>
      <p class="muted pad">Kommt im nächsten Schritt:</p>
      <ul class="list">
        {COMING.map((c) => (
          <li class="card row soon">
            <Icon name={c.icon} />
            <div>
              <strong>{c.title}</strong>
              <p class="meta">{c.text}</p>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
