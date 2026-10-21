// Call and radar history (A3, A4) arrive with step 4.
import { can, type User } from "../api";

export function History({ user }: { user: User }) {
  if (!can(user, "logs")) return <p class="muted pad">Für dich gibt es hier nichts.</p>;
  return (
    <div class="pad">
      <p class="muted">Kommt bald: wer wann was über Tür und RoomKeys gesagt hat, wann jemand vor der Tür stand, und die
        gemalten Bilder von der Tür.</p>
    </div>
  );
}
