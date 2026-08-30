# Python 3.14 is required: src/euroleague/mcp/db.py uses PEP 758 exception
# syntax, which older interpreters cannot parse. A platform's default runtime
# is not new enough, so the version is pinned in the image.
# The digest, not the tag, is what actually pins this. `python:3.14-slim` is
# rebuilt and republished under the same tag whenever its Debian base changes, so
# the tag alone means two builds a week apart are two different images. The tag
# stays in the comment because a bare digest is unreadable, and Dependabot moves
# the digest forward - a digest pin receives no security patches on its own.
FROM python:3.14-slim@sha256:cae66f2ef0ec51a9891263eeee7f987dacf0a9879e8aa9353d5606e0530619a5

# Run as a non-root user. Nothing here needs root, and a container that cannot
# write to its own filesystem is one less thing to reason about.
RUN useradd --create-home --uid 10001 appuser

WORKDIR /app

COPY requirements.txt requirements-http.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-http.txt

COPY src/ ./src/
COPY scripts/mcp_http_server.py ./scripts/
COPY pyproject.toml ./

USER appuser

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080

EXPOSE 8080

CMD ["python", "scripts/mcp_http_server.py"]
