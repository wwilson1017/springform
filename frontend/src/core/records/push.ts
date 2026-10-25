/**
 * Web Push in this browser: register `/sw.js`, ask permission, subscribe with the server's VAPID
 * key, and POST the subscription; or the reverse. Native browser APIs only. The service worker
 * is registered only when the user opts in.
 *
 * Lifted from CakeCRM's pushSubscription.ts (itself from Chatty), on Springform's routes.
 */
import { del, fetchJson, postJson } from '../api/client';
import { NOTIFICATIONS } from './notifications';
import type { PushPublicKey } from './types';

const SW = '/sw.js';

export const pushSupported = () =>
  typeof navigator !== 'undefined' && 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window;

/** This browser's current subscription, if it has one. */
export async function currentSubscription(): Promise<PushSubscription | null> {
  if (!pushSupported()) return null;
  const registration = await navigator.serviceWorker.getRegistration(SW);
  return registration ? registration.pushManager.getSubscription() : null;
}

function keyBytes(base64url: string): ArrayBuffer {
  const base64 = (base64url + '='.repeat((4 - (base64url.length % 4)) % 4)).replace(/-/g, '+').replace(/_/g, '/');
  return Uint8Array.from(atob(base64), c => c.charCodeAt(0)).buffer;
}

/** Subscribe this browser. Resolves false when the user refuses permission. */
export async function enablePush(): Promise<boolean> {
  const registration = await navigator.serviceWorker.register(SW);
  await navigator.serviceWorker.ready;
  if (await Notification.requestPermission() !== 'granted') return false;
  const { public_key } = await fetchJson<PushPublicKey>(`${NOTIFICATIONS}/push/public-key`);
  const subscription = await registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(public_key) });
  const { endpoint, keys } = subscription.toJSON();
  await postJson(`${NOTIFICATIONS}/push/subscribe`, { endpoint, keys: { p256dh: keys?.p256dh, auth: keys?.auth } });
  return true;
}

/** Unsubscribe this browser and tell the server to forget it. */
export async function disablePush(): Promise<void> {
  const subscription = await currentSubscription();
  if (!subscription) return;
  const { endpoint } = subscription;
  await subscription.unsubscribe();
  await del(`${NOTIFICATIONS}/push/subscribe`, { endpoint });
}
