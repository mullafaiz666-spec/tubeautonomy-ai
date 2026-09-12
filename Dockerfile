FROM node:22-bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    espeak-ng \
    fonts-dejavu-core \
    ca-certificates \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# The standalone TubeAutonomy v0.2.0 source is stored as a compact,
# deterministic base64 bundle because this repository was initialized
# without the application source. Reconstruct it before installing deps.
COPY bundle /tmp/tube-bundle
RUN cat /tmp/tube-bundle/source.part* | base64 -d > /tmp/source.tgz \
  && tar -xzf /tmp/source.tgz -C /app --strip-components=1 \
  && rm -rf /tmp/tube-bundle /tmp/source.tgz

RUN npm ci --no-audit --no-fund

ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

RUN mkdir -p /var/tube/data /var/tube/output \
  && chown -R node:node /var/tube /app

USER node
ENV NODE_ENV=production \
    DATA_DIR=/var/tube/data \
    OUTPUT_DIR=/var/tube/output \
    PORT=10000

EXPOSE 10000
CMD ["npm","start"]
