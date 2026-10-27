FROM python:3.12-slim
RUN apt-get update \
 && apt-get install -y --no-install-recommends git openssh-client ca-certificates curl ripgrep \
 && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.9.11 /uv /bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PATH="/app/.venv/bin:$PATH" PLURAL_DATA_DIR=/data
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev
COPY deploy/host-entrypoint.sh /usr/local/bin/plural-host-entrypoint
RUN chmod +x /usr/local/bin/plural-host-entrypoint
VOLUME /data
ENTRYPOINT ["plural-host-entrypoint"]
