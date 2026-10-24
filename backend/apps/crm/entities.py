from backend.core.entities import Entity, title_from

# Any active member reads and writes any deal (the Entity defaults); the registry adds the
# manifest's role check, which keeps the system principal read-only.
ENTITIES = [
    Entity(
        type="crm.deal", table="crm_deals", label="Deal", label_plural="Deals",
        url_fn=lambda deal_id: f"/crm/deals/{deal_id}", title_fn=title_from("crm_deals", "title"),
        searchable=("title", "notes"), archived_column="archived_at",
    ),
]
