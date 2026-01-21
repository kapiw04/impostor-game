# Impostor

FastAPI + Redis backend for a simple "secret word" game.

## Configuration

Environment variables are loaded automatically from a local `.env` file (if present).  
Copy the template and adjust the values to match your setup:

```bash
cp .env.example .env
```

`REDIS_URL` defaults to `redis://redis:6379/0` so the docker-compose Redis service works out of the box.  
For local development against a host Redis instance use `redis://localhost:6379/0`.

## Run it

Requires Python 3.12 and Redis.

```bash
export REDIS_URL=<your_redis_url>
uv run fastapi dev impostor/main.py --host 0.0.0.0 --port 8000
```

Or with Docker:

```bash
docker compose up --build
```

You can also build and run the container directly:

```bash
docker build -t impostor .
docker run --env-file .env -p 8000:8000 impostor
```

## Tests

Uses testcontainers to spin up Redis.

```bash
uv run pytest
```
