# The PDF report renderer (React PDF, run with Node by the report worker).
FROM node:22-slim AS pdf-renderer
WORKDIR /pdf-renderer
COPY pdf-renderer/package.json pdf-renderer/package-lock.json ./
RUN npm ci
COPY pdf-renderer/ ./
RUN npm run build && npm prune --omit=dev

FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Node (copied below) links against libstdc++, which the slim image leaves out.
RUN apt-get update && apt-get install -y --no-install-recommends libstdc++6 && rm -rf /var/lib/apt/lists/*

# Dependencies first so code changes do not invalidate this layer.
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
COPY --from=pdf-renderer /usr/local/bin/node /usr/local/bin/node
COPY --from=pdf-renderer /pdf-renderer/dist pdf-renderer/dist
COPY --from=pdf-renderer /pdf-renderer/node_modules pdf-renderer/node_modules

# Never run as root inside the container.
RUN useradd --create-home --uid 10001 app && chown -R app /app
USER app

EXPOSE 8000

# --proxy-headers: behind a load balancer the rate limiter must see the real client address.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
