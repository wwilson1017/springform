import { createContext, useContext } from 'react';

/** The signed-in user, as the Todos screens need it. The App (and each record panel) provides it
 *  from the core auth context; without a provider (a unit test) nobody is signed in. */
export interface Me {
  id: number | null;
  isAdmin: boolean;
}

export const MeContext = createContext<Me>({ id: null, isAdmin: false });

export const useMe = (): Me => useContext(MeContext);
