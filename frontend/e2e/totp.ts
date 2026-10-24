import { createHmac } from 'node:crypto';

/**
 * RFC 6238 codes (SHA-1, 6 digits, 30 s), what pyotp computes on the server. The server reads time
 * from its frozen clock, so tests pass that instant (E2E_FREEZE_CLOCK) and pick the step.
 */
export function totp(secret: string, at: Date, stepOffset = 0): string {
  const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';
  let bits = '';
  for (const ch of secret.replace(/=+$/, '').toUpperCase()) bits += alphabet.indexOf(ch).toString(2).padStart(5, '0');
  const key = Buffer.from(bits.match(/.{8}/g)!.map(b => parseInt(b, 2)));
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(Math.floor(at.getTime() / 30_000) + stepOffset));
  const mac = createHmac('sha1', key).update(counter).digest();
  const offset = mac[mac.length - 1] & 0xf;
  return String((mac.readUInt32BE(offset) & 0x7fffffff) % 1_000_000).padStart(6, '0');
}

/** The instant the server's clock is frozen at, or now when the backend runs a live clock. */
export function serverNow(): Date {
  return process.env.E2E_FREEZE_CLOCK ? new Date(process.env.E2E_FREEZE_CLOCK) : new Date();
}
