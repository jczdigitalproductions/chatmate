# Runs the agent as a background worker. It needs outbound internet only:
#   docker build -t chatmatefetcher .
#   docker run -d --restart unless-stopped --env-file .env chatmatefetcher
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1
WORKDIR /app

COPY pyproject.toml uv.lock* ./
RUN uv sync --no-dev --no-install-project

COPY . .
CMD ["uv", "run", "--no-dev", "python", "agent.py"]
