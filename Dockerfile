FROM node:20-slim AS frontend
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM python:3.12-slim
WORKDIR /app

COPY review_scraper/requirements.txt review_scraper/requirements.txt
RUN pip install --no-cache-dir -r review_scraper/requirements.txt

COPY review_scraper/ review_scraper/
COPY --from=frontend /app/dist dist/

# server.py uses relative imports (from normalize import ...), so add to path
ENV PYTHONPATH=/app/review_scraper
# cache.db lives on the persistent volume, mounted at /data
ENV DB_PATH=/data/cache.db

EXPOSE 8080
CMD ["gunicorn", "server:app", "--chdir", "/app/review_scraper", "--bind", "0.0.0.0:8080", "--timeout", "120", "--workers", "2"]
