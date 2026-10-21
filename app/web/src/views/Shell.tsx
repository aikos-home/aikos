// The signed-in app (rule A20): status on top, one page per tab, tabs at the bottom: Tür · Nachrichten · Verlauf · Haus.
import { useEffect, useState } from "preact/hooks";
import { api, type DoorStatus, type User } from "../api";
import { clock, hhmm } from "../format";
import { Door } from "./Door";
import { History } from "./History";
import { House } from "./House";
import { Icon } from "./Icon";
import { Messages } from "./Messages";

const TABS = [
  { id: "tuer", label: "Tür", icon: "door" },
  { id: "nachrichten", label: "Nachrichten", icon: "message" },
  { id: "verlauf", label: "Verlauf", icon: "history" },
  { id: "haus", label: "Haus", icon: "home" },
] as const;
type Tab = (typeof TABS)[number]["id"];
const TITLES: Record<Tab, string> = { tuer: "Tür", nachrichten: "Nachrichten", verlauf: "Verlauf", haus: "Haus" };
const STATUS_EVERY_MS = 10_000;

const tabFromHash = (): Tab => (TABS.find((t) => `#${t.id}` === location.hash)?.id ?? "nachrichten");

export function Shell({ user, onSignedOut }: { user: User; onSignedOut: () => void }) {
  const [tab, setTab] = useState<Tab>(tabFromHash());
  const [status, setStatus] = useState<DoorStatus | null>(null);

  useEffect(() => {
    const onHash = () => setTab(tabFromHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  useEffect(() => {
    let alive = true;
    const load = () => api.doorStatus().then((s) => alive && setStatus(s)).catch(() => undefined);
    load();
    const timer = setInterval(load, STATUS_EVERY_MS);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, []);

  const go = (t: Tab) => {
    history.replaceState(null, "", `#${t}`);
    setTab(t);
  };

  return (
    <div class="shell">
      <header class="topbar">
        <h1>{TITLES[tab]}</h1>
        <span class="grow" />
        <StatusChips status={status} />
        <button class="avatar" aria-label="Haus und Profil" onClick={() => go("haus")}>
          {user.name.slice(0, 1).toUpperCase()}
        </button>
      </header>
      {status && !status.ha_connected && <div class="strip warn">Home Assistant ist gerade nicht erreichbar.</div>}
      {status?.someone_at_door && (
        <div class="strip ok">
          <Icon name="radar" /> Jemand steht vor der Tür{status.someone_since ? ` · seit ${clock(status.someone_since)}` : ""}
        </div>
      )}
      <main class="content">
        {tab === "tuer" && <Door user={user} />}
        {tab === "nachrichten" && <Messages user={user} />}
        {tab === "verlauf" && <History user={user} />}
        {tab === "haus" && <House user={user} onSignedOut={onSignedOut} />}
      </main>
      <nav class="tabbar">
        {TABS.map((t) => (
          <button class={tab === t.id ? "active" : ""} onClick={() => go(t.id)} aria-current={tab === t.id}>
            <Icon name={t.icon} />
            <span>{t.label}</span>
          </button>
        ))}
      </nav>
    </div>
  );
}

function StatusChips({ status }: { status: DoorStatus | null }) {
  if (!status) return null;
  return (
    <>
      {status.bell_muted !== null && (
        <span class={`chip ${status.bell_muted ? "warn" : ""}`}>
          <Icon name={status.bell_muted ? "bell-off" : "bell"} /> {status.bell_muted ? "Stumm" : "Klingel an"}
        </span>
      )}
      {status.quiet_hours !== null && (
        <span class={`chip ${status.quiet_hours ? "warn" : ""}`}>
          <Icon name="moon" />{" "}
          {status.quiet_hours ? `Ruhe bis ${hhmm(status.quiet_end)}` : `ab ${hhmm(status.quiet_start)}`}
        </span>
      )}
    </>
  );
}
