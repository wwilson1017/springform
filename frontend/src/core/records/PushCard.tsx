/** Settings → Notifications → Push notifications: turn push on or off for this browser. */
import { useEffect, useState } from 'react';
import { ApiError } from '../api/client';
import { toast } from '../../shared/toast';
import { currentSubscription, disablePush, enablePush, pushSupported } from './push';
import { BTN_PRIMARY, BTN_SECONDARY, MUTED, errorText } from './ui';

type State = 'checking' | 'unsupported' | 'blocked' | 'on' | 'off';

export default function PushCard() {
  const [state, setState] = useState<State>('checking');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!pushSupported()) { queueMicrotask(() => setState('unsupported')); return; }
    currentSubscription().then(
      sub => setState(sub ? 'on' : Notification.permission === 'denied' ? 'blocked' : 'off'),
      () => setState('off'),
    );
  }, []);

  async function toggle() {
    setBusy(true);
    try {
      if (state === 'on') {
        await disablePush();
        setState('off');
      } else if (await enablePush()) {
        setState('on');
        toast.success('Push notifications are on for this browser.');
      } else {
        setState(Notification.permission === 'denied' ? 'blocked' : 'off');
      }
    } catch (err) {
      // 503 push_unavailable: the server's VAPID key can't be read (see backend notifications/push.py).
      toast.error(err instanceof ApiError && err.detail === 'push_unavailable'
        ? 'Push is unavailable on this server right now.'
        : errorText(err, "Couldn't change push notifications in this browser."));
    } finally {
      setBusy(false);
    }
  }

  const text: Record<State, string> = {
    checking: 'Checking this browser…',
    unsupported: "This browser can't receive push notifications. On iPhone, add Springform to the home screen first.",
    blocked: 'Notifications are blocked for this site. Allow them in the browser settings, then come back.',
    on: 'On for this browser. Notifications arrive even when Springform is closed.',
    off: 'Get your notifications on this device even when Springform is closed.',
  };

  return (
    <div className="flex flex-col gap-3">
      <p className={MUTED}>{text[state]}</p>
      {(state === 'on' || state === 'off') && (
        <button type="button" disabled={busy} onClick={() => void toggle()} className={`${state === 'on' ? BTN_SECONDARY : BTN_PRIMARY} w-fit`}>
          {busy ? 'Working…' : state === 'on' ? 'Turn off in this browser' : 'Turn on in this browser'}
        </button>
      )}
    </div>
  );
}
