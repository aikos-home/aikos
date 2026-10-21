// Push on this device (A24): the browser's push subscription, registered with the app. The push carries text only, never
// sound (G5); the phone's service worker turns it into the notification.
import { api } from "./api";

export type PushState = "unsupported" | "needs-install" | "denied" | "off" | "on";

const ios = () => /iPhone|iPad|iPod/.test(navigator.userAgent);
const installed = () =>
  matchMedia("(display-mode: standalone)").matches || (navigator as { standalone?: boolean }).standalone === true;
const supported = () => "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;

function bytes(b64u: string): Uint8Array<ArrayBuffer> {
  const s = atob(b64u.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - (b64u.length % 4)) % 4));
  const out = new Uint8Array(new ArrayBuffer(s.length));
  for (let i = 0; i < s.length; i++) out[i] = s.charCodeAt(i);
  return out;
}

function sameKey(a: ArrayBuffer | null | undefined, b: Uint8Array): boolean {
  if (!a) return false;
  const x = new Uint8Array(a);
  return x.length === b.length && x.every((v, i) => v === b[i]);
}

function deviceLabel(): string {
  const ua = navigator.userAgent;
  if (/Android/.test(ua)) return "Android";
  if (/iPhone|iPad/.test(ua)) return "iPhone";
  if (/Windows/.test(ua)) return "Windows";
  if (/Mac/.test(ua)) return "Mac";
  return "Browser";
}

export async function pushState(): Promise<PushState> {
  if (!supported()) return ios() && !installed() ? "needs-install" : "unsupported";
  if (Notification.permission === "denied") return "denied";
  const sub = await (await navigator.serviceWorker.ready).pushManager.getSubscription();
  return sub && Notification.permission === "granted" ? "on" : "off";
}

export async function pushOn(): Promise<PushState> {
  const permission = await Notification.requestPermission();
  if (permission !== "granted") return permission === "denied" ? "denied" : "off";
  const reg = await navigator.serviceWorker.ready;
  const key = bytes((await api.pushKey()).key);
  let sub = await reg.pushManager.getSubscription();
  if (sub && !sameKey(sub.options.applicationServerKey, key)) {
    await sub.unsubscribe();
    sub = null;
  }
  sub = sub ?? (await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: key }));
  await api.pushSubscribe(sub.toJSON(), deviceLabel());
  return "on";
}

export async function pushOff(): Promise<PushState> {
  const sub = supported() ? await (await navigator.serviceWorker.ready).pushManager.getSubscription() : null;
  if (sub) {
    await api.pushUnsubscribe(sub.endpoint).catch(() => undefined);
    await sub.unsubscribe();
  }
  return "off";
}

/** At every start: tell the app about this device's subscription again (it forgets phones the push service dropped). */
export async function syncPush(): Promise<void> {
  if (!supported() || Notification.permission !== "granted") return;
  const sub = await (await navigator.serviceWorker.ready).pushManager.getSubscription();
  if (sub) await api.pushSubscribe(sub.toJSON(), deviceLabel()).catch(() => undefined);
}
