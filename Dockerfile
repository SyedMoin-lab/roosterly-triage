FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_IN_PROJECT=true

RUN pip install --no-cache-dir "poetry==2.5.1"

WORKDIR /app
COPY pyproject.toml poetry.lock poetry.toml README.md ./
COPY src ./src
COPY data ./data
RUN poetry install --only main && rm -rf /root/.cache

RUN useradd --create-home agent && chown -R agent /app
USER agent

ENTRYPOINT ["/app/.venv/bin/python", "-m", "triage"]
CMD ["run"]
