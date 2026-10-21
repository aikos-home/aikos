// The app's only door to aikos: /api/v1 on the same origin. No Home Assistant address ever appears here (rule G3).

export type Role = "superadmin" | "adult" | "child";

export interface User {
  id: number;
  name: string;
  role: Role;
  ha_person: string;
  capabilities: string[];
}

export interface DoorMessage {
  id: string;
  content_type: string;
  time: string;
  seconds: number | null;
  text: string;
  recipient: string;
  speaker: string;
  heard_by: string[];
  /** I have heard it (kept in Home Assistant). */
  heard: boolean;
  /** A38: recipient or superadmin; for everyone: adults too. */
  may_delete: boolean;
  audio_missing: boolean;
  audio: string | null;
}

export interface DoorStatus {
  someone_at_door: boolean | null;
  someone_since: number | null;
  quiet_hours: boolean | null;
  quiet_start: string;
  quiet_end: string;
  bell_muted: boolean | null;
  ha_connected: boolean;
}

export interface Passkey {
  id: string;
  label: string;
  created_at: number;
  last_used_at: number | null;
}

export interface Person extends User {
  disabled: boolean;
}

export interface Ceremony {
  flow: string;
  options: any;
}

const MESSAGES: Record<string, string> = {
  invalid_code: "Der Einrichtungscode stimmt nicht oder ist abgelaufen.",
  invalid_name: "Bitte einen Namen mit höchstens 40 Zeichen eingeben.",
  already_set_up: "aikos ist schon eingerichtet. Bitte anmelden.",
  flow_expired: "Das hat zu lange gedauert. Bitte noch einmal.",
  passkey_failed: "Der Passkey wurde nicht bestätigt.",
  unknown_passkey: "Diesen Passkey kennt aikos nicht.",
  invite_invalid: "Die Einladung ist ungültig, abgelaufen oder schon benutzt.",
  invalid_role: "Unbekannte Rolle.",
  slow_down: "Zu viele Versuche. Bitte in ein paar Minuten noch einmal.",
  ha_unreachable: "Home Assistant ist gerade nicht erreichbar.",
  ha_error: "Home Assistant hat einen Fehler gemeldet.",
  forbidden: "Das darfst du nicht.",
  not_found: "Gibt es nicht (mehr).",
  last_passkey_or_unknown: "Der letzte Passkey kann nicht gelöscht werden.",
  cannot_disable_self: "Du kannst dich nicht selbst sperren.",
  bad_origin: "Anfrage von einer fremden Seite abgelehnt.",
  network: "Keine Verbindung zu aikos.",
  no_register: "Dafür braucht Home Assistant die aikos-Integration ab 0.8.0.",
};

export class ApiError extends Error {
  constructor(public code: string, public status: number) {
    super(MESSAGES[code] ?? `Fehler (${code})`);
  }
}

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      method,
      credentials: "same-origin",
      headers: body === undefined ? {} : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError("network", 0);
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new ApiError(data.error ?? "unknown", response.status);
  return data as T;
}

export const api = {
  setupStatus: () => call<{ needs_setup: boolean }>("GET", "/api/v1/setup"),
  setupStart: (code: string, name: string) => call<Ceremony>("POST", "/api/v1/setup/start", { code, name }),
  setupFinish: (flow: string, credential: unknown) =>
    call<{ user: User }>("POST", "/api/v1/setup/finish", { flow, credential }),
  loginStart: () => call<Ceremony>("POST", "/api/v1/login/start"),
  loginFinish: (flow: string, credential: unknown) =>
    call<{ user: User }>("POST", "/api/v1/login/finish", { flow, credential }),
  inviteInfo: (token: string) =>
    call<{ name: string; role: Role; kind: "new" | "device"; expires_at: number }>("POST", "/api/v1/invites/info", { token }),
  inviteStart: (token: string) => call<Ceremony>("POST", "/api/v1/invites/start", { token }),
  inviteFinish: (flow: string, credential: unknown) =>
    call<{ user: User }>("POST", "/api/v1/invites/finish", { flow, credential }),
  me: () => call<User>("GET", "/api/v1/me"),
  logout: () => call<{ ok: boolean }>("POST", "/api/v1/logout"),
  logoutAll: () => call<{ ok: boolean }>("POST", "/api/v1/logout/all"),
  passkeys: () => call<Passkey[]>("GET", "/api/v1/me/passkeys"),
  addPasskeyStart: () => call<Ceremony>("POST", "/api/v1/me/passkeys/start"),
  addPasskeyFinish: (flow: string, credential: unknown) =>
    call<{ ok: boolean }>("POST", "/api/v1/me/passkeys/finish", { flow, credential }),
  deletePasskey: (id: string) => call<{ ok: boolean }>("DELETE", `/api/v1/me/passkeys/${encodeURIComponent(id)}`),
  people: () => call<Person[]>("GET", "/api/v1/people"),
  invite: (name: string, role: Role, ha_person: string) =>
    call<{ link: string; expires_at: number }>("POST", "/api/v1/people/invites", { name, role, ha_person }),
  deviceInvite: (userId: number) =>
    call<{ link: string; expires_at: number }>("POST", `/api/v1/people/${userId}/device-invite`),
  disablePerson: (userId: number) => call<{ ok: boolean }>("POST", `/api/v1/people/${userId}/disable`),
  doorStatus: () => call<DoorStatus>("GET", "/api/v1/door/status"),
  doorMessages: () => call<DoorMessage[]>("GET", "/api/v1/door/messages"),
  deleteMessage: (id: string) => call<unknown>("DELETE", `/api/v1/door/messages/${encodeURIComponent(id)}`),
  messageHeard: (id: string) => call<unknown>("POST", `/api/v1/door/messages/${encodeURIComponent(id)}/heard`),
};

export const can = (user: User, cap: string) => user.capabilities.includes(cap);

export const ROLE_NAMES: Record<Role, string> = { superadmin: "Superadmin", adult: "Erwachsene", child: "Kind" };
