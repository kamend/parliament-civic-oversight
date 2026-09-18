# Parliament RAG backend — FastAPI service over the LanceDB index.
#
# Build context is ./backend. Data (LanceDB index + transcripts) and the
# HuggingFace model cache are NOT baked in — they are mounted at runtime as
# volumes (see ../docker-compose.yml) so the ~5 GB of model weights and the
# regenerable index live outside the image.
FROM python:3.12-slim

# uv: fast, reproducible installs from the committed uv.lock.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Copy = no hardlinks across the layer boundary; bytecode = faster cold starts.
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    PYTHONUNBUFFERED=1

# Dependency layer — cached unless pyproject.toml / uv.lock change. `package =
# false` in pyproject means there's no project to install, only its deps.
# The cache mount keeps uv's downloaded wheels out of the image layer (they'd
# otherwise double the size, stored alongside the installed venv).
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# Application code (changes most often → last).
COPY parl_rag ./parl_rag

# Run the venv's binaries directly, no `uv run` wrapper needed.
ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8077

CMD ["uvicorn", "parl_rag.api.main:app", "--host", "0.0.0.0", "--port", "8077"]
