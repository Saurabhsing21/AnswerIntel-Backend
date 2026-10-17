FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies first so code changes do not invalidate this layer.
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Never run as root inside the container.
RUN useradd --create-home --uid 10001 app && chown -R app /app
USER app

EXPOSE 8000

# --proxy-headers: behind a load balancer the rate limiter must see the real client address.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
