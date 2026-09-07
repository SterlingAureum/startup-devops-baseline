FROM python:3.12-slim AS base

ARG APP_UID=10001
ARG APP_GID=10001

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_VERSION=0.1.0 \
    APP_ENV=local \
    HOME=/home/demo-api \
    TMPDIR=/tmp

WORKDIR /app

RUN apt-get update \
    && apt-get upgrade --yes \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid "${APP_GID}" demo-api \
    && useradd \
        --uid "${APP_UID}" \
        --gid "${APP_GID}" \
        --create-home \
        --home-dir /home/demo-api \
        --shell /usr/sbin/nologin \
        demo-api

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=${APP_UID}:${APP_GID} src/ ./src/

FROM base AS test

COPY --chown=${APP_UID}:${APP_GID} tests/ ./tests/

RUN python -m unittest discover --start-directory tests --verbose

FROM base AS runtime

USER 10001:10001

EXPOSE 8080

CMD ["python", "-m", "src.server"]
