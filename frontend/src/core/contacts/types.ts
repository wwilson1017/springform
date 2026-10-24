/**
 * Shapes of `/api/core/contacts` (backend/core/contacts/{router,service}.py). The routes return
 * plain dicts, so there are no generated response types to lean on; these mirror the service.
 */

export type ContactKind = 'person' | 'organization';

/** What a picker holds: enough to show and link a record. */
export interface ContactRef {
  id: number;
  name: string;
}

interface RecordBase {
  id: number;
  name: string;
  /** Mirrors the primary email channel; written only by the server. */
  email: string | null;
  /** Mirrors the primary phone channel; written only by the server. */
  phone: string | null;
  source: string | null;
  status: string | null;
  tags: string[];
  notes: string | null;
  owner_user_id: number | null;
  archived_at: string | null;
  merged_into_id: number | null;
  created_at: string;
  updated_at: string;
}

export interface Person extends RecordBase {
  given_name: string | null;
  family_name: string | null;
  title: string | null;
}

/** A row of GET /people. */
export interface PersonRow extends Person {
  primary_organization_id: number | null;
  primary_organization_name: string | null;
}

export interface Organization extends RecordBase {
  domain: string | null;
  website: string | null;
  industry: string | null;
}

export type ContactRecord = Person | Organization;

export type ChannelKind = 'email' | 'phone' | 'url' | 'other';

export interface Channel {
  id: number;
  owner_type: ContactKind;
  owner_id: number;
  kind: ChannelKind;
  value: string;
  label: string | null;
  is_primary: boolean;
}

export interface Address {
  id: number;
  owner_type: ContactKind;
  owner_id: number;
  kind: string | null;
  line1: string | null;
  line2: string | null;
  city: string | null;
  region: string | null;
  postal_code: string | null;
  country: string | null;
  is_primary: boolean;
}

interface LinkBase {
  name: string;
  archived_at: string | null;
  role: string;
  /** The person's primary organization (one per person). */
  is_primary: boolean;
  started_on: string | null;
  ended_on: string | null;
}

/** A person's organization, on the person's detail (primary first). */
export interface OrganizationLink extends LinkBase {
  organization_id: number;
}

/** An organization's person, on the organization's detail. */
export interface PersonLink extends LinkBase {
  person_id: number;
  email: string | null;
  phone: string | null;
  title: string | null;
}

interface DetailParts {
  channels: Channel[];
  addresses: Address[];
}

export interface PersonDetail extends Person, DetailParts {
  organizations: OrganizationLink[];
}

export interface OrganizationDetail extends Organization, DetailParts {
  people: PersonLink[];
}

export type ContactDetail = PersonDetail | OrganizationDetail;

/** GET /people/{id} of a merged id answers 200 with the survivor instead of the record. */
export interface MergedAway {
  merged_into: number;
}

export interface ContactPage<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface SearchHit {
  kind: ContactKind;
  id: number;
  name: string;
  email: string | null;
  phone: string | null;
  url: string;
}

export interface DuplicateGroup {
  match_on: 'email' | 'phone' | 'name' | 'domain';
  value: string;
  count: number;
  records: Array<{ id: number; label: string }>;
}

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
