# SPDX-License-Identifier: GPL-3.0-or-later
# Image for the API and the worker. Build context is the repository root (see docker-compose.yml).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# tzdata: so that TZ works (the schedule uses local time). fonts: needed by the renderer.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# Run as a normal user. /data holds the images and firmware files (Docker volumes).
RUN useradd --create-home --uid 1000 bert \
    && mkdir -p /data/images /data/firmware_bins \
    && chown -R bert:bert /data

WORKDIR /app
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY backend/ /app/
RUN chmod +x /app/docker-entrypoint.sh

USER bert
ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["api"]