import type { UserRef } from '../../core/api/types';
import { useJson } from '../../core/api/useJson';
import { usersUrl } from './api';

/** Active users anyone may list (the mention directory), for owner pickers and filters. */
export function useUsers(): UserRef[] {
  return useJson<UserRef[]>(usersUrl).data ?? [];
}
