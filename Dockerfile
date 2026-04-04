FROM python:3.13-slim

RUN pip install --no-cache-dir uv

WORKDIR /app

COPY pyproject.toml ./
RUN uv pip install --system --no-cache \
    "flask>=3.1" \
    "flask-caching>=2.3" \
    "gunicorn>=23.0" \
    "peewee>=3.17" \
    "psycopg2-binary>=2.9" \
    "python-dotenv>=1.0" \
    "redis>=5.0" \
    "faker>=33.0"

COPY . .

RUN chmod +x entrypoint.sh

EXPOSE 5000

ENTRYPOINT ["./entrypoint.sh"]
