#!/bin/sh
set -e

echo "Waiting for database to be ready..."
python - <<'EOF'
import os, sys, time
import psycopg2

host = os.environ.get("DATABASE_HOST", "db")
port = int(os.environ.get("DATABASE_PORT", 5432))
user = os.environ.get("DATABASE_USER", "postgres")
password = os.environ.get("DATABASE_PASSWORD", "postgres")
dbname = os.environ.get("DATABASE_NAME", "hackathon_db")

for attempt in range(30):
    try:
        conn = psycopg2.connect(host=host, port=port, user=user, password=password, dbname=dbname)
        conn.close()
        print("Database is ready!")
        sys.exit(0)
    except psycopg2.OperationalError as e:
        print(f"Attempt {attempt + 1}/30: waiting... ({e})")
        time.sleep(2)

print("Database not ready after 60 seconds, exiting.")
sys.exit(1)
EOF

# echo "Seeding database..."
# python -c "from app.seed import seed_all; seed_all()"

echo "Starting application with Gunicorn..."
exec gunicorn \
  --workers "${GUNICORN_WORKERS:-4}" \
  --bind "0.0.0.0:${PORT:-5000}" \
  --timeout 120 \
  --access-logfile - \
  --error-logfile - \
  "app:create_app()"
