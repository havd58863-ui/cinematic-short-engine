# syntax=docker/dockerfile:1.7
FROM python:3.12-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258

ARG REQUIREMENTS_LOCK=requirements/locks/core.txt
ARG APT_PACKAGES="ca-certificates ffmpeg fonts-noto-core git libgomp1 libsndfile1"
ARG UV_VERSION=0.13.3

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PREFECT_SERVER_ANALYTICS_ENABLED=0 \
    ENGINE_CONFIG_DIR=/app/config \
    HF_HOME=/app/.cache/huggingface \
    MPLCONFIGDIR=/tmp/matplotlib

RUN apt-get update \
    && apt-get install -y --no-install-recommends ${APT_PACKAGES} \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 engine

WORKDIR /app

COPY ${REQUIREMENTS_LOCK} /tmp/requirements.txt
RUN python -m pip install --no-cache-dir "uv==${UV_VERSION}" \
    && uv pip install --system --break-system-packages --index-strategy unsafe-best-match -r /tmp/requirements.txt

COPY pyproject.toml README.md ./
COPY src ./src
RUN uv pip install --system --break-system-packages --no-deps .

COPY --chown=engine:engine config ./config
COPY --chown=engine:engine docs ./docs
COPY --chown=engine:engine scripts ./scripts
COPY --chown=engine:engine vendor/openmontage.lock.json vendor/README_VENDOR.md ./vendor/
RUN mkdir -p /app/.cache/huggingface /app/.prefect /app/runs \
    && chown -R engine:engine /app/.cache /app/.prefect /app/runs

USER engine
ENTRYPOINT ["cinematic-engine"]
CMD ["doctor", "--json"]
