# Container image for MCP registry/directory evaluation (Glama and similar),
# which start the server and issue introspection requests.
#
# NOTE ON REAL USE: this server reads the Adversaria desktop app's SQLite
# database from your machine, so a container is not the natural way to run it —
# use `uv run adversaria-mcp` on the host instead (see README). If you do run
# the image, mount the database and point ADVERSARIA_DB at it:
#
#   docker run -i --rm \
#     -v "$HOME/Library/Application Support/meeting-note-taker:/data:ro" \
#     -e ADVERSARIA_DB=/data/meetings.db adversaria-mcp
#
# The server starts and lists its tools with no database present; the tools
# themselves report a clear error until one is available.

FROM python:3.11-slim

# Don't buffer stdout — the MCP stdio transport needs responses to flush.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY adversaria_mcp ./adversaria_mcp

RUN pip install --no-cache-dir .

# Run as a non-root user; the server only ever needs read access.
RUN useradd --create-home --uid 10001 mcp
USER mcp

ENTRYPOINT ["adversaria-mcp"]
