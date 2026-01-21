FROM python:3.12-slim
WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock ./

RUN uv sync --frozen
COPY . .

ARG REDIS_URL=redis://redis:6379/0
ENV REDIS_URL=${REDIS_URL}

CMD ["uv", "run", "fastapi", "dev", "impostor/main.py", "--host", "0.0.0.0", "--port", "8000"]
