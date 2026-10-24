/**
 * First-run setup: the one-time token from the server log (or a `?token=` link) creates the
 * first admin. The server answers 404 once setup is done or for a wrong token.
 */

import { useState, type FormEvent } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router';
import { ApiError, postJson } from '../api/client';
import { useAuth } from './AuthContext';
import { AuthLayout, buttonClass, inputClass, labelClass } from './AuthLayout';

function setupError(err: unknown): string {
  if (!(err instanceof ApiError)) return "Can't reach the server. Try again in a moment.";
  if (err.status === 404) return 'Setup is not available: it is already done, or the token is wrong.';
  if (err.status === 422) return 'Check the fields: a valid email, your name, and a longer password.';
  return "Couldn't finish setup. Try again.";
}

export function SetupPage() {
  const { refresh } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [form, setForm] = useState({ token: params.get('token') ?? '', email: '', name: '', password: '' });
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError('');
    setBusy(true);
    try {
      await postJson('/api/auth/setup', form);
      await refresh();
      navigate('/', { replace: true });
    } catch (err) {
      setError(setupError(err));
    } finally {
      setBusy(false);
    }
  }

  const field = (key: keyof typeof form, label: string, type: string, autoComplete: string) => (
    <div className="mb-4">
      <label htmlFor={`setup-${key}`} className={labelClass}>{label}</label>
      <input id={`setup-${key}`} type={type} autoComplete={autoComplete} value={form[key]} className={inputClass}
        onChange={e => setForm(f => ({ ...f, [key]: e.target.value }))} />
    </div>
  );

  return (
    <AuthLayout subtitle="Create the first admin account.">
      <form onSubmit={onSubmit}>
        {field('token', 'Setup token', 'text', 'off')}
        {field('email', 'Email', 'email', 'username')}
        {field('name', 'Name', 'text', 'name')}
        {field('password', 'Password', 'password', 'new-password')}
        {error && <p role="alert" className="mb-0 text-sm text-sf-red-text">{error}</p>}
        <button type="submit" disabled={busy || Object.values(form).some(v => !v)} className={`${buttonClass} mt-2`}>
          {busy ? 'Creating…' : 'Create admin'}
        </button>
      </form>
      <p className="mt-6 text-center text-sm"><Link to="/login" className="text-sf-accent-text">Back to sign in</Link></p>
    </AuthLayout>
  );
}
