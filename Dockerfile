FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates libgomp1 ffmpeg \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /srv
COPY requirements.txt .
RUN pip install -r requirements.txt

# Obico open-source failure-detection model (AGPL-3.0, https://github.com/TheSpaghettiDetective/obico-server)
ARG MODEL_URL=https://www.obico.io/static_pub/ml-models/model-weights-5a6b1be1fa.onnx
ARG MODEL_SHA256=0a6ebd8e30dbf6a450c50f9c0a5406f04ba7eb1c99fd5996e888c78bb383b9aa
RUN mkdir -p /models \
 && curl -fsSL --retry 3 "$MODEL_URL" -o /models/failure.onnx \
 && echo "$MODEL_SHA256  /models/failure.onnx" | sha256sum -c -

COPY app/ ./app/

EXPOSE 8080
CMD ["python", "-m", "app.main"]
