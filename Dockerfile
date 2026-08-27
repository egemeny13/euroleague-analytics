# Python 3.14 is required: src/euroleague/mcp/db.py uses PEP 758 exception
# syntax, which older interpreters cannot parse. A platform's default runtime
# is not new enough, so the version is pinned in the image.
FROM python:3.14-slim

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
