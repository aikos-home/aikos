// The frame of the signed-out screens (setup, login, invite).
import type { ComponentChildren } from "preact";

export function Welcome({ title, children }: { title: string; children: ComponentChildren }) {
  return (
    <main class="welcome">
      <img src="/icon-192.png" alt="" width={72} height={72} class="logo" />
      <h1>{title}</h1>
      {children}
    </main>
  );
}

export function NoPasskeys() {
  return (
    <p class="note warn">
      Dieser Browser kann hier keine Passkeys nutzen. aikos braucht eine sichere Verbindung (HTTPS) und einen aktuellen
      Browser.
    </p>
  );
}
