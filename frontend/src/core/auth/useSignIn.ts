import { useCallback, useState } from 'react';
import { useNavigate } from 'react-router';
import { useAuth } from './AuthContext';
import { needsChallenge, type LoginResult } from './api';

/**
 * The end of every first factor (password, preview, invite, reset): either the cookie is set and
 * the user goes home, or 2FA is on and the page switches to the challenge step.
 * Each returns an error message, or '' when it navigated.
 */
export function useSignIn(initialChallenge: string | null = null) {
  const { refresh } = useAuth();
  const navigate = useNavigate();
  const [challenge, setChallenge] = useState(initialChallenge);

  const enter = useCallback(async () => {
    // The cookie is set; /api/me is the one source of who that is.
    if (await refresh()) {
      navigate('/', { replace: true });
      return '';
    }
    return "Signed in, but couldn't load your account. Reload the page.";
  }, [refresh, navigate]);

  const finish = useCallback(async (result: LoginResult) => {
    if (needsChallenge(result)) {
      setChallenge(result.challenge);
      return '';
    }
    return enter();
  }, [enter]);

  return { challenge, setChallenge, finish, enter };
}
