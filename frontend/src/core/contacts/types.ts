/** Shapes of `/api/core/contacts`, from the generated schemas. */
import type { components } from '../api/types.gen';

type S = components['schemas'];

export type ContactKind = 'person' | 'organization';

/** What a picker holds: enough to show and link a record. */
export interface ContactRef {
  id: number;
  name: string;
}

/** A row of GET /people. `email` and `phone` mirror the primary channels; only the server writes them. */
export type PersonRow = S['PersonRow'];
export type Organization = S['OrganizationRecord'];
/** A row of either list. */
export type ContactRecord = PersonRow | Organization;

export type Channel = S['Channel'];
export type ChannelKind = Channel['kind'];
export type Address = S['Address'];

/** A person's organization, on the person's detail (primary first). */
export type OrganizationLink = S['OrganizationLink'];
/** An organization's person, on the organization's detail. */
export type PersonLink = S['PersonLink'];

export type PersonDetail = S['PersonDetail'];
export type OrganizationDetail = S['OrganizationDetail'];
export type ContactDetail = PersonDetail | OrganizationDetail;

/** GET /people/{id} of a merged id answers 200 with the survivor instead of the record. */
export type MergedAway = S['MergedAway'];

export type PersonPage = S['PersonPage'];
export type OrganizationPage = S['OrganizationPage'];
export type ContactSearchHit = S['ContactSearchHit'];
export type ContactDuplicates = S['ContactDuplicates'];

/**
 * What a record page hands each of its sections. `entityType`/`entityId` match RecordPanelProps,
 * so a core record component (Timeline, Attachments, RecordServices) is a section as it is.
 */
export interface SectionProps {
  kind: ContactKind;
  record: ContactDetail;
  entityType: string;
  entityId: number;
  /** Refetch the record after a write that changes it (its mirrored email/phone, its links). */
  reload: () => void;
}
