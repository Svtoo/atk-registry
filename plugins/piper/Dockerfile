FROM python:3.11-slim

WORKDIR /app

# Install curl for healthcheck and piper-tts with HTTP support
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir piper-tts[http]

# Models directory - will be mounted as volume for persistence
RUN mkdir -p /app/models

# Default voice (can be overridden via environment variable)
ENV PIPER_VOICE=en_GB-alba-medium
ENV PIPER_DATA_DIR=/app/models

EXPOSE 5000

# Entrypoint script that downloads voice if needed and starts server
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

CMD ["/app/entrypoint.sh"]

