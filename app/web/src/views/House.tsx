// Haus: my profile and passkeys; for the superadmin the people and invites; space for the RoomKeys (A18).
import { useEffect, useState } from "preact/hooks";
import { api, can, ROLE_NAMES, type Passkey, type Person, type Role, type User } from "../api";
import { addPasskey, errorText } from "../passkey";
import { Icon } from "./Icon";

export function House({ user, onSignedOut }: { user: User; onSignedOut: () => void }) {
  return (
    <div>
      <Profile user={user} onSignedOut={onSignedOut} />
      {can(user, "people.manage") && <People me={user} />}
      <section class="pad">
        <h2>RoomKeys</h2>
        <p class="muted">Kommt mit den RoomKeys: Klingeltöne, Einstellungen deines Zimmers, Durchsagen.</p>
      </section>
    </div>
  );
}

function Profile({ user, onSignedOut }: { user: User; onSignedOut: () => void }) {
  const [keys, setKeys] = useState<Passkey[]>([]);
  const [msg, setMsg] = useState("");
  const load = () => api.passkeys().then(setKeys).catch((e) => setMsg(errorText(e)));
  useEffect(() => {
    load();
  }, []);

  const add = async () => {
    setMsg("");
    try {
      await addPasskey();
      setMsg("Passkey hinzugefügt.");
      load();
    } catch (e) {
      setMsg(errorText(e));
    }
  };
  const remove = async (id: string) => {
    try {
      await api.deletePasskey(id);
      load();
    } catch (e) {
      setMsg(errorText(e));
    }
  };
  const out = async (all: boolean) => {
    await (all ? api.logoutAll() : api.logout()).catch(() => undefined);
    onSignedOut();
  };

  return (
    <section class="pad">
      <div class="row">
        <span class="avatar big">{user.name.slice(0, 1).toUpperCase()}</span>
        <div>
          <strong>{user.name}</strong>
          <p class="meta">{ROLE_NAMES[user.role]}</p>
        </div>
      </div>
      <h2>Passkeys</h2>
      <ul class="list plain">
        {keys.map((k) => (
          <li class="row line">
            <Icon name="key" />
            <span>{k.label || "Passkey"}</span>
            <span class="meta">seit {new Date(k.created_at * 1000).toLocaleDateString("de-DE")}</span>
            <span class="grow" />
            {keys.length > 1 && <button class="link" onClick={() => remove(k.id)}>Entfernen</button>}
          </li>
        ))}
      </ul>
      <div class="row gap">
        <button onClick={add}><Icon name="plus" /> Passkey für dieses Gerät</button>
      </div>
      {msg && <p class="meta">{msg}</p>}
      <div class="row gap">
        <button onClick={() => out(false)}>Abmelden</button>
        <button onClick={() => out(true)}>Überall abmelden</button>
      </div>
    </section>
  );
}

function People({ me }: { me: User }) {
  const [people, setPeople] = useState<Person[]>([]);
  const [name, setName] = useState("");
  const [role, setRole] = useState<Role>("adult");
  const [haPerson, setHaPerson] = useState("");
  const [link, setLink] = useState("");
  const [msg, setMsg] = useState("");
  const load = () => api.people().then(setPeople).catch((e) => setMsg(errorText(e)));
  useEffect(() => {
    load();
  }, []);

  const invite = async (e: Event) => {
    e.preventDefault();
    setMsg("");
    if (!name.trim()) return setMsg("Bitte einen Namen eingeben.");
    try {
      setLink((await api.invite(name.trim(), role, haPerson.trim())).link);
      setName("");
      setHaPerson("");
    } catch (err) {
      setMsg(errorText(err));
    }
  };
  const device = async (p: Person) => {
    try {
      setLink((await api.deviceInvite(p.id)).link);
    } catch (err) {
      setMsg(errorText(err));
    }
  };
  const block = async (p: Person) => {
    if (!confirm(`${p.name} sperren? Alle Anmeldungen enden sofort.`)) return;
    try {
      await api.disablePerson(p.id);
      load();
    } catch (err) {
      setMsg(errorText(err));
    }
  };
  const share = async () => {
    const canShare = "share" in navigator;
    try {
      if (canShare) await navigator.share({ title: "aikos", text: "Deine Einladung zu aikos", url: link });
      else await navigator.clipboard.writeText(link);
      setMsg(canShare ? "" : "Link kopiert.");
    } catch {
      // closing the share sheet is fine
    }
  };

  return (
    <section class="pad">
      <h2>Personen</h2>
      <ul class="list plain">
        {people.map((p) => (
          <li class="row line">
            <Icon name="user" />
            <span class={p.disabled ? "muted strike" : ""}>{p.name}</span>
            <span class="meta">{ROLE_NAMES[p.role]}</span>
            <span class="grow" />
            {!p.disabled && <button class="link" onClick={() => device(p)}>Neues Gerät</button>}
            {!p.disabled && p.id !== me.id && <button class="link danger" onClick={() => block(p)}>Sperren</button>}
          </li>
        ))}
      </ul>
      <form class="stack" onSubmit={invite}>
        <h3>Einladen</h3>
        <label>Name<input value={name} onInput={(e) => setName(e.currentTarget.value)} maxLength={40} /></label>
        <label>Rolle
          <select value={role} onChange={(e) => setRole(e.currentTarget.value as Role)}>
            <option value="adult">Erwachsene</option>
            <option value="child">Kind</option>
            <option value="superadmin">Superadmin</option>
          </select>
        </label>
        <label>Person in Home Assistant (optional)
          <input value={haPerson} onInput={(e) => setHaPerson(e.currentTarget.value)} placeholder="person.…" />
        </label>
        <button class="primary">Einladung erstellen</button>
      </form>
      {link && (
        <div class="note">
          <p>Einladung (24 h gültig, einmal):</p>
          <code class="break">{link}</code>
          <div class="row gap"><button onClick={share}>Teilen</button></div>
        </div>
      )}
      {msg && <p class="meta">{msg}</p>}
    </section>
  );
}
