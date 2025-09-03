# Multi-stage build for better optimization
FROM agnohq/python:3.12 AS base

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_CACHE_DIR=/tmp/uv-cache \
    UV_HTTP_TIMEOUT=120

# Create non-root user
ARG USER=app
ARG UID=61000
ARG GID=61000
ARG APP_DIR=/app

RUN groupadd -g ${GID} ${USER} \
    && useradd -g ${GID} -u ${UID} -ms /bin/bash -d ${APP_DIR} ${USER}

# Development stage for dependencies
FROM base AS deps

WORKDIR ${APP_DIR}

# Copy dependency files first for better layer caching
COPY requirements.txt pyproject.toml ./

# Install dependencies with uv for faster installation
RUN uv pip sync requirements.txt --system \
    && uv cache clean

# Production stage
FROM base AS production

WORKDIR ${APP_DIR}

# Copy installed packages from deps stage
COPY --from=deps /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin

# Copy application code
COPY --chown=${USER}:${USER} . .

# Create necessary directories and set permissions
RUN mkdir -p /tmp/uv-cache /var/log/app \
    && chown -R ${USER}:${USER} ${APP_DIR} /tmp/uv-cache /var/log/app

# Switch to non-root user
USER ${USER}

# Expose port
EXPOSE 8000

# Use exec form for better signal handling
ENTRYPOINT ["/app/scripts/entrypoint.sh"]
CMD ["chill"]
