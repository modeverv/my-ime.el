FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MY_IME_BACKEND=kkc \
    MY_IME_KKC_COMMAND=/usr/bin/kkc \
    MY_IME_KKC_MODEL=sorted3 \
    MY_IME_HOST=0.0.0.0 \
    MY_IME_PORT=8765

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        libkkc-data \
        libkkc-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md ./
COPY server ./server
COPY data ./data

RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir . \
    && command -v kkc \
    && test -d /usr/lib/*/libkkc/models/sorted3

EXPOSE 8765

CMD ["my-ime-server"]
