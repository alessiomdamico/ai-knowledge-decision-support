FROM node:22-bookworm-slim AS frontend
WORKDIR /build
COPY package*.json ./
RUN npm ci
COPY web ./web
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
COPY requirements*.txt ./
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r requirements-models.txt \
    && useradd --create-home --uid 10001 hub \
    && mkdir -p /app/data /models && chown hub:hub /app/data /models
COPY hub ./hub
COPY --from=frontend /build/dist ./dist
ENV HUB_DB=/app/data/hub.sqlite3 HF_HOME=/models HF_HUB_DISABLE_TELEMETRY=1
USER hub
EXPOSE 8769
CMD ["python", "-m", "uvicorn", "hub.app:app", "--host", "0.0.0.0", "--port", "8769", "--no-access-log"]
