FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev
EXPOSE 8787
CMD ["uv", "run", "--no-sync", "plural", "relay", "--bind", "0.0.0.0", "--port", "8787"]
