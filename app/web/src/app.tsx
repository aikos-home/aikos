// Which screen: invite link → invite; nobody set up → setup; not signed in → login; else the app with tabs.
import { useEffect, useState } from "preact/hooks";
import { api, ApiError, type User } from "./api";
import { Invite } from "./views/Invite";
import { Login } from "./views/Login";
import { Setup } from "./views/Setup";
import { Shell } from "./views/Shell";

type Screen = { kind: "loading" } | { kind: "setup" } | { kind: "login" } | { kind: "invite"; token: string }
  | { kind: "app"; user: User } | { kind: "offline" };

export function App() {
  const [screen, setScreen] = useState<Screen>({ kind: "loading" });

  const signedIn = (user: User) => {
    if (location.pathname !== "/") history.replaceState(null, "", "/#nachrichten");
    setScreen({ kind: "app", user });
  };

  const decide = async () => {
    if (location.pathname === "/einladung") {
      const token = location.hash.slice(1);
      if (token) return setScreen({ kind: "invite", token });
    }
    try {
      return setScreen({ kind: "app", user: await api.me() });
    } catch (e) {
      if (!(e instanceof ApiError) || e.status !== 401) return setScreen({ kind: "offline" });
    }
    try {
      const { needs_setup } = await api.setupStatus();
      setScreen({ kind: needs_setup ? "setup" : "login" });
    } catch {
      setScreen({ kind: "offline" });
    }
  };

  useEffect(() => {
    decide();
  }, []);

  switch (screen.kind) {
    case "loading":
      return <div class="center muted">aikos …</div>;
    case "offline":
      return (
        <div class="center">
          <p>Keine Verbindung zu aikos.</p>
          <button onClick={decide}>Noch einmal</button>
        </div>
      );
    case "setup":
      return <Setup onDone={signedIn} />;
    case "login":
      return <Login onDone={signedIn} />;
    case "invite":
      return <Invite token={screen.token} onDone={signedIn} onLogin={() => {
        history.replaceState(null, "", "/");
        setScreen({ kind: "login" });
      }} />;
    case "app":
      return <Shell user={screen.user} onSignedOut={() => setScreen({ kind: "login" })} />;
  }
}
