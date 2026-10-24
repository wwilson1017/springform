-- Contacts: one primary channel per owner and kind, one primary address per owner. Enforced
-- like core_person_organizations_primary; the service demotes the old primary first.
CREATE UNIQUE INDEX core_contact_channels_primary ON core_contact_channels (owner_type, owner_id, kind) WHERE is_primary = 1;
CREATE UNIQUE INDEX core_addresses_primary ON core_addresses (owner_type, owner_id) WHERE is_primary = 1;
