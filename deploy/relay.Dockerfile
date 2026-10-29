FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.9.11 /uv /bin/uv
RUN useradd --system --create-home --uid 10001 plural
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PATH="/app/.venv/bin:$PATH" PORT=8787 PLURAL_RELAY_BIND=0.0.0.0 PLURAL_RELAY_PROXY_HOPS=1
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev
RUN mkdir -p /data && chown plural /data
USER plural
EXPOSE 8787
CMD ["plural-host", "relay"]
