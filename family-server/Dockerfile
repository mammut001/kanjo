FROM python:3.14-slim

# Create non-root system user and group
RUN groupadd -r nonroot && useradd -r -g nonroot -d /home/nonroot -m nonroot

WORKDIR /app

# Ensure /data exists and is owned by nonroot
RUN mkdir -p /data && chown -R nonroot:nonroot /data /home/nonroot

# Copy application package
COPY family_server/ /app/family_server/

ENV PYTHONUNBUFFERED=1
ENV FAMILY_DB=/data/family.db

USER nonroot

EXPOSE 8787 8788

CMD ["python", "-m", "family_server", "serve"]
