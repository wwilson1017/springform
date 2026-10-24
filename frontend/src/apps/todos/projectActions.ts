// Todo GTD — shared project close-out action (one definition
// used by the Projects card grid and the project detail header, so the
// Complete/Reactivate flow can't drift between the two).
import { updateProject } from './api';
import { toast } from './toast';
import type { TodoProjectStatus } from './types';

/** PUT a project status change; toasts on failure. Returns success. */
export async function updateProjectStatus(
  projectId: number, status: TodoProjectStatus,
): Promise<boolean> {
  try {
    await updateProject(projectId, { status });
    return true;
  } catch {
    toast.error('Failed to update project.');
    return false;
  }
}
