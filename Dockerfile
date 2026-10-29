# syntax=docker/dockerfile:1
# AVDP GIS Portal application image (GeoNode 5.1.1 + project customisations).
# GEONODE_BASE_IMAGE is pinned by digest in .env; the default below matches
# the base image used by GeoNode 5.1.1 / geonode-project 5.1.x.
ARG GEONODE_BASE_IMAGE=geonode/geonode-base:latest-ubuntu-24.04
FROM ${GEONODE_BASE_IMAGE}

ENV LC_ALL=C.UTF-8 \
    LANG=C.UTF-8
WORKDIR /usr/src/project

RUN apt-get update -y && apt-get install -y --no-install-recommends \
    curl \
    wget \
    unzip \
    gnupg2 \
    locales \
    netcat-openbsd \
    && sed -i -e 's/# C.UTF-8 UTF-8/C.UTF-8 UTF-8/' /etc/locale.gen \
    && locale-gen \
    && apt-get autoremove --purge -y \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Optional: networks with a TLS-intercepting proxy can supply its CA bundle as
# a BuildKit secret named "extra_ca" (see docs/DEVELOPMENT.md). Nothing is
# stored in the image; without the secret the build uses the system CAs.
RUN --mount=type=secret,id=extra_ca,required=false \
    if [ -s /run/secrets/extra_ca ]; then export PIP_CERT=/run/secrets/extra_ca; fi \
    && python -m pip install --no-cache-dir -U pip setuptools wheel

COPY src/wait-for-databases.sh /usr/bin/wait-for-databases
COPY src/celery.sh /usr/bin/celery-commands
COPY src/celery-cmd /usr/bin/celery-cmd
RUN chmod +x /usr/bin/wait-for-databases /usr/bin/celery-commands /usr/bin/celery-cmd

# Install dependencies first so that code-only changes reuse the cached layer.
COPY src/pyproject.toml /usr/src/project/pyproject.toml
RUN --mount=type=secret,id=extra_ca,required=false \
    if [ -s /run/secrets/extra_ca ]; then export PIP_CERT=/run/secrets/extra_ca; fi \
    && mkdir -p /usr/src/project/geonode_project \
    && touch /usr/src/project/geonode_project/__init__.py \
    && yes w | pip install --no-cache-dir -e .

COPY src/ /usr/src/project/
RUN chmod +x /usr/src/project/tasks.py /usr/src/project/entrypoint.sh \
    && pip install --no-cache-dir --no-deps --no-build-isolation -e .

EXPOSE 8000
