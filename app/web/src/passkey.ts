// Passkey ceremonies in the browser. The server holds the challenge; the browser only signs.
import { browserSupportsWebAuthn, startAuthentication, startRegistration } from "@simplewebauthn/browser";
import { api, ApiError, type Ceremony, type User } from "./api";

export const passkeysAvailable = () => window.isSecureContext && browserSupportsWebAuthn();

function cancelled(e: unknown): boolean {
  return e instanceof Error && (e.name === "NotAllowedError" || e.name === "AbortError");
}

export class PasskeyCancelled extends Error {
  constructor() {
    super("Abgebrochen.");
  }
}

async function register<T>(start: Promise<Ceremony>, finish: (flow: string, credential: unknown) => Promise<T>) {
  const { flow, options } = await start;
  let credential;
  try {
    credential = await startRegistration({ optionsJSON: options });
  } catch (e) {
    if (cancelled(e)) throw new PasskeyCancelled();
    if (e instanceof Error && e.name === "InvalidStateError") throw new Error("Dieses Gerät hat schon einen Passkey für dich.");
    throw e;
  }
  return finish(flow, credential);
}

export async function login(): Promise<User> {
  const { flow, options } = await api.loginStart();
  let credential;
  try {
    credential = await startAuthentication({ optionsJSON: options });
  } catch (e) {
    if (cancelled(e)) throw new PasskeyCancelled();
    throw e;
  }
  return (await api.loginFinish(flow, credential)).user;
}

export const setup = (code: string, name: string) =>
  register(api.setupStart(code, name), api.setupFinish).then((r) => r.user);

export const redeemInvite = (token: string) =>
  register(api.inviteStart(token), api.inviteFinish).then((r) => r.user);

export const addPasskey = () => register(api.addPasskeyStart(), api.addPasskeyFinish);

export const errorText = (e: unknown) =>
  e instanceof ApiError || e instanceof PasskeyCancelled || e instanceof Error ? e.message : "Unbekannter Fehler.";
