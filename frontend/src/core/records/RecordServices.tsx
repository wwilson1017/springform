import { CustomFields } from './CustomFields';
import { RemindersPanel } from './RemindersPanel';

export interface RecordServicesProps {
  entityType: string;
  entityId: number;
}

/**
 * The record services every record page shows beside its own fields: custom fields (nothing
 * when the type has none) and reminders. Timeline and Attachments stay separate so a page can
 * place them in its own columns.
 */
export function RecordServices({ entityType, entityId }: RecordServicesProps) {
  return (
    <div className="flex flex-col gap-8">
      <CustomFields entityType={entityType} entityId={entityId} />
      <RemindersPanel entityType={entityType} entityId={entityId} />
    </div>
  );
}
