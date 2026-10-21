// Haus: my profile and passkeys; for the superadmin the people and invites; space for the RoomKeys (A18).
import { useEffect, useState } from "preact/hooks";
import { api, can, ROLE_NAMES, type Passkey, type Person, type Role, type User } from "../api";
import { addPasskey, errorText } from "../passkey";
import { Icon } from "./Icon";
import { LinkPanel } from "./LinkPanel";

const DEVICE_HINT = "Mit der Kamera des Handys scannen, die Seite öffnet sich, dort „Passkey anlegen“. Gilt 24 h und einmal; "
  + "ein neuer Code macht den alten ungültig.";

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
  const [phoneLink, setPhoneLink] = useState("");
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
  const phone = async () => {
    setMsg("");
    try {
      setPhoneLink((await api.deviceInvite(user.id)).link);
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
        {can(user, "people.manage") && <button class="primary" onClick={phone}><Icon name="plus" /> Handy hinzufügen</button>}
        <button onClick={add}><Icon name="plus" /> Passkey für dieses Gerät</button>
      </div>
      {phoneLink && <LinkPanel link={phoneLink} title="Passkey für dein Handy" hint={DEVICE_HINT}
                               onClose={() => { setPhoneLink(""); load(); }} />}
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
  const [deviceFor, setDeviceFor] = useState<{ id: number; link: string } | null>(null);
  const [inviteLink, setInviteLink] = useState("");
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
      setInviteLink((await api.invite(name.trim(), role, haPerson.trim())).link);
      setName("");
      setHaPerson("");
    } catch (err) {
      setMsg(errorText(err));
    }
  };
  const device = async (p: Person) => {
    setMsg("");
    try {
      setDeviceFor({ id: p.id, link: (await api.deviceInvite(p.id)).link });
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

  return (
    <section class="pad">
      <h2>Personen</h2>
      <ul class="list plain">
        {people.map((p) => (
          <li>
            <div class="row line">
              <Icon name="user" />
              <span class={p.disabled ? "muted strike" : ""}>{p.name}</span>
              <span class="meta">{ROLE_NAMES[p.role]}</span>
              <span class="grow" />
              {!p.disabled && <button class="link" onClick={() => device(p)}>Neues Gerät</button>}
              {!p.disabled && p.id !== me.id && <button class="link danger" onClick={() => block(p)}>Sperren</button>}
            </div>
            {deviceFor?.id === p.id && (
              <LinkPanel link={deviceFor.link} title={`Neues Gerät für ${p.name}`} hint={DEVICE_HINT}
                         onClose={() => setDeviceFor(null)} />
            )}
          </li>
        ))}
      </ul>
      {msg && <p class="meta">{msg}</p>}
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
      {inviteLink && (
        <LinkPanel link={inviteLink} title="Einladung" onClose={() => setInviteLink("")}
                   hint="Mit dem Handy der Person scannen oder den Link schicken. Gilt 24 h und einmal." />
      )}
    </section>
  );
}
