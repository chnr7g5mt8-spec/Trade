# One container serving both the rating API and the web version of the app.
#   docker build -t stock-rater .
#   docker run -p 8000:8000 stock-rater                        # live Yahoo data
#   docker run -p 8000:8000 -e DATA_SOURCE=sample stock-rater  # demo data

# --- Build the web app -------------------------------------------------------
FROM node:22-slim AS web
WORKDIR /mobile
# Offline: the build needs nothing from Expo's servers.
ENV CI=1 EXPO_NO_TELEMETRY=1 EXPO_OFFLINE=1
COPY mobile/package.json mobile/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY mobile/ ./
RUN npx expo export --platform web --output-dir /web

# --- Runtime -----------------------------------------------------------------
FROM python:3.13-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 WEB_DIR=/app/web PORT=8000
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app ./app
COPY --from=web /web ./web
RUN useradd --create-home appuser
USER appuser
EXPOSE 8000
# Hosts such as Render tell the app which port to use through $PORT.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port \"$PORT\" --proxy-headers --forwarded-allow-ips='*'"]
