"""Sample people and organizations for PREVIEW_MODE. Every name, address, email and phone is
made up (example.com addresses, 555-01xx numbers)."""

from backend.core.auth.deps import User
from backend.core.contacts import service

ORGANIZATIONS = [
    {"name": "Example Bakery Supply", "domain": "bakery.example.com", "industry": "Wholesale", "tags": ["supplier"]},
    {"name": "Sample Dairy Co-op", "domain": "dairy.example.com", "industry": "Dairy", "tags": ["supplier"]},
    {"name": "Demo Café Group", "domain": "cafe.example.com", "industry": "Hospitality", "tags": ["customer"]},
    {"name": "Placeholder Grocers", "domain": "grocers.example.com", "industry": "Retail", "tags": ["customer"]},
    {"name": "Fictional Events Ltd", "domain": "events.example.com", "industry": "Events", "tags": ["customer"]},
]
# (name, email, phone, title, organization, role)
PEOPLE = [
    ("Ada Example", "ada@bakery.example.com", "555-0101", "Owner", "Example Bakery Supply", "Owner"),
    ("Grace Sample", "grace@dairy.example.com", "555-0102", "Buyer", "Sample Dairy Co-op", "Buyer"),
    ("Zoë Démo", "zoe@cafe.example.com", "555-0103", "Manager", "Demo Café Group", "Manager"),
    ("Linus Placeholder", "linus@grocers.example.com", "555-0104", "Purchasing", "Placeholder Grocers", "Purchasing"),
    ("Marie Fictional", "marie@events.example.com", "555-0105", "Planner", "Fictional Events Ltd", "Planner"),
    ("Alan Testcase", "alan@cafe.example.com", "555-0106", "Chef", "Demo Café Group", "Chef"),
    ("Ada Example", "ada@bakery.example.com", None, None, None, None),  # a duplicate to merge
]


def sample(conn) -> None:
    """Writes through the service as the first admin; does nothing once any contact exists."""
    if conn.execute("SELECT 1 FROM core_people UNION ALL SELECT 1 FROM core_organizations LIMIT 1").fetchone():
        return
    row = conn.execute("SELECT * FROM core_users WHERE role = 'admin' AND is_active = 1 ORDER BY id LIMIT 1").fetchone()
    if row is None:
        return
    admin = User.from_row(row)
    orgs = {o["name"]: service.create_in(conn, admin, "organization", o)["id"] for o in ORGANIZATIONS}
    service.add_part_in(
        conn, admin, "address", "organization", orgs["Example Bakery Supply"],
        kind="work", line1="1 Sample Street", city="Exampleville", postal_code="00001", country="US",
    )
    for name, email, phone, title, org, role in PEOPLE:
        person = service.create_in(conn, admin, "person", {"name": name, "email": email, "phone": phone, "title": title})
        if org:
            service.link_in(conn, admin, person["id"], orgs[org], role)
    ada = conn.execute("SELECT id FROM core_people WHERE name = 'Ada Example' ORDER BY id LIMIT 1").fetchone()[0]
    service.link_in(conn, admin, ada, orgs["Demo Café Group"], "Supplier contact")
