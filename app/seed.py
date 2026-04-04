import csv
import os

from dotenv import load_dotenv
from peewee import chunked


def _parse_bool(value):
    return str(value).strip().lower() in ("true", "1", "yes")


def _load_users(db, User, filepath):
    with open(filepath, newline="") as f:
        rows = list(csv.DictReader(f))

    data = [
        {
            "id": int(r["id"]),
            "username": r["username"],
            "email": r["email"],
            "created_at": r["created_at"],
        }
        for r in rows
    ]

    with db.atomic():
        for batch in chunked(data, 100):
            User.insert_many(batch).execute()

    # Reset sequence so future inserts don't conflict
    max_id = max(r["id"] for r in data)
    db.execute_sql(f"SELECT setval(pg_get_serial_sequence('users', 'id'), {max_id})")
    print(f"  Loaded {len(data)} users")


def _load_urls(db, Url, filepath):
    with open(filepath, newline="") as f:
        rows = list(csv.DictReader(f))

    data = [
        {
            "id": int(r["id"]),
            "user_id": int(r["user_id"]) if r.get("user_id") else None,
            "short_code": r["short_code"],
            "original_url": r["original_url"],
            "title": r.get("title") or None,
            "is_active": _parse_bool(r["is_active"]),
            "created_at": r["created_at"],
            "updated_at": r["updated_at"],
        }
        for r in rows
    ]

    with db.atomic():
        for batch in chunked(data, 100):
            Url.insert_many(batch).execute()

    max_id = max(r["id"] for r in data)
    db.execute_sql(f"SELECT setval(pg_get_serial_sequence('urls', 'id'), {max_id})")
    print(f"  Loaded {len(data)} URLs")


def _load_events(db, Event, filepath):
    with open(filepath, newline="") as f:
        rows = list(csv.DictReader(f))

    data = [
        {
            "id": int(r["id"]),
            "url_id": int(r["url_id"]),
            "user_id": int(r["user_id"]) if r.get("user_id") else None,
            "event_type": r["event_type"],
            "timestamp": r["timestamp"],
            "details": r.get("details") or None,
        }
        for r in rows
    ]

    with db.atomic():
        for batch in chunked(data, 100):
            Event.insert_many(batch).execute()

    max_id = max(r["id"] for r in data)
    db.execute_sql(f"SELECT setval(pg_get_serial_sequence('events', 'id'), {max_id})")
    print(f"  Loaded {len(data)} events")


def seed_all():
    load_dotenv()

    from app import create_app

    app = create_app()

    from app.database import db
    from app.models.event import Event
    from app.models.url import Url
    from app.models.user import User

    db.connect(reuse_if_open=True)

    print("Creating tables...")
    db.create_tables([User, Url, Event], safe=True)

    if User.select().count() > 0:
        print("Database already seeded, skipping.")
        db.close()
        return

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    users_csv = os.path.join(base_dir, "users.csv")
    urls_csv = os.path.join(base_dir, "urls.csv")
    events_csv = os.path.join(base_dir, "events.csv")

    print("Seeding users...")
    _load_users(db, User, users_csv)

    print("Seeding URLs...")
    _load_urls(db, Url, urls_csv)

    print("Seeding events...")
    _load_events(db, Event, events_csv)

    db.close()
    print("Seeding complete!")


if __name__ == "__main__":
    seed_all()
