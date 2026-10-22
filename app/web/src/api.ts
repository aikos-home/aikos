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
  quiet_enabled: boolean | null;
  bell_muted: boolean | null;
  /** ISO; "" while muted = until switched off. */
  bell_muted_until: string;
  ha_connected: boolean;
}

export interface DoorAnnouncements {
  now: string;   // "none", or the situations one after the other, e.g. "quiet+parcel" (aikos 0.16.0)
  now_text: string;
  disclosure: number;
  parcel: string;
  away: string;
  quiet: string;
  away_places: string;
  places: Record<string, string>;
  voice: boolean;
  ready: string[];
  last: { situation?: string; text?: string; at?: string };
  zones: { id: string; name: string }[];
  residents: { id: string; name: string; named: boolean }[];
  me: { resident: boolean; named: boolean };
}

export interface DoorCall {
  active: boolean;
  call_id: string;
  messages: { id: string; side: "door" | "room"; who: string; text: string; tr: string; tr_lang: string }[];
  ring: string;
  talk: boolean;
}

export interface DoorActionsState {
  note: { message: string; sender: string; since: string } | null;
  greeting: { state: "active" | "scheduled" | "off"; enabled: boolean; text: string; start: string; end: string; audio: boolean };
  picture: boolean;
  quick: string[];
  announcements: DoorAnnouncements | null;
}

export interface MyVoice {
  available: boolean;
  voice: { seconds: number | null; created: number | null } | null;
  reading: string;
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
  bad_subscription: "Dieses Gerät lässt sich nicht für Benachrichtigungen anmelden.",
  no_voice_service: "Der Sprachdienst des Hauses ist nicht eingerichtet.",
  voice_service_unreachable: "Der Sprachdienst des Hauses antwortet gerade nicht.",
  voice_service_error: "Der Sprachdienst hat einen Fehler gemeldet.",
  voice_recording: "Die Aufnahme ging nicht: bitte mindestens 15 Sekunden am Stück vorlesen.",
  no_voice: "Du hast noch keine Stimme aufgenommen.",
  no_door_actions: "Dafür braucht Home Assistant die aikos-Integration ab 0.9.0.",
  invalid: "Home Assistant hat das nicht angenommen.",
  bad_type: "Diese Datei passt nicht.",
  too_large: "Die Datei ist zu groß.",
  no_register: "Dafür braucht Home Assistant die aikos-Integration ab 0.8.0.",
};

export class ApiError extends Error {
  constructor(public code: string, public status: number) {
    super(MESSAGES[code] ?? `Fehler (${code})`);
  }
}

async function upload<T = void>(method: string, path: string, blob: Blob): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      method, credentials: "same-origin", headers: { "Content-Type": blob.type.split(";")[0] }, body: blob,
    });
  } catch {
    throw new ApiError("network", 0);
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new ApiError(data.error ?? (response.status === 413 ? "too_large" : "unknown"), response.status);
  return data as T;
}

async function binary(method: string, path: string, body?: unknown): Promise<Blob> {
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
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new ApiError(data.error ?? "unknown", response.status);
  }
  return response.blob();
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
  doorActions: () => call<DoorActionsState | null>("GET", "/api/v1/door/actions"),
  doorCall: () => call<DoorCall>("GET", "/api/v1/door/call"),
  bell: (body: { minutes?: number; until_time?: string; forever?: boolean; off?: boolean }) =>
    call<unknown>("POST", "/api/v1/door/bell", body),
  quietHours: (body: { enabled?: boolean; start?: string; end?: string }) =>
    call<unknown>("POST", "/api/v1/door/quiet-hours", body),
  say: (message: string) => call<{ delivered: "now" | "waiting" }>("POST", "/api/v1/door/say", { message }),
  cancelSay: () => call<unknown>("DELETE", "/api/v1/door/say"),
  sayDraft: (message: string) => call<unknown>("POST", "/api/v1/door/say/draft", { message }),
  putPicture: (blob: Blob) => upload("PUT", "/api/v1/door/picture", blob),
  deletePicture: () => call<unknown>("DELETE", "/api/v1/door/picture"),
  putGreeting: (body: { enabled?: boolean; text?: string; start?: string; end?: string; always?: boolean }) =>
    call<unknown>("PUT", "/api/v1/door/greeting", body),
  putGreetingAudio: (blob: Blob) => upload("PUT", "/api/v1/door/greeting/audio", blob),
  myVoice: () => call<MyVoice>("GET", "/api/v1/me/voice"),
  putMyVoice: (blob: Blob) => upload<{ seconds: number; created: number }>("PUT", "/api/v1/me/voice", blob),
  deleteMyVoice: () => call<unknown>("DELETE", "/api/v1/me/voice"),
  myVoiceSample: (text?: string) => binary("POST", "/api/v1/me/voice/sample", text ? { text } : undefined),
  putAnnouncements: (body: { disclosure?: number; parcel?: string; away?: string; quiet?: string; away_places?: string;
    places?: Record<string, string>; name_me?: boolean }) => call<unknown>("PUT", "/api/v1/door/announcements", body),
  deleteGreetingAudio: () => call<unknown>("DELETE", "/api/v1/door/greeting/audio"),
  deleteMessage: (id: string) => call<unknown>("DELETE", `/api/v1/door/messages/${encodeURIComponent(id)}`),
  pushKey: () => call<{ key: string }>("GET", "/api/v1/push/key"),
  pushSubscribe: (subscription: PushSubscriptionJSON, label: string) =>
    call<{ ok: boolean }>("POST", "/api/v1/push/subscription", { ...subscription, label }),
  pushUnsubscribe: (endpoint: string) => call<{ ok: boolean }>("DELETE", "/api/v1/push/subscription", { endpoint }),
  pushTest: () => call<{ sent: number }>("POST", "/api/v1/push/test"),
  messageHeard: (id: string) => call<unknown>("POST", `/api/v1/door/messages/${encodeURIComponent(id)}/heard`),
};

export const can = (user: User, cap: string) => user.capabilities.includes(cap);

export const ROLE_NAMES: Record<Role, string> = { superadmin: "Superadmin", adult: "Erwachsene", child: "Kind" };
