# ---- Stage 1: build the frontend (Node) ------------------------------------
FROM node:20-alpine AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---- Stage 2: serve (Python) -----------------------------------------------
FROM python:3.12-slim
WORKDIR /app

COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/ backend/
COPY --from=frontend /app/frontend/dist frontend/dist

# Default to the deterministic mock so a plain `docker run` works with no
# external LLM. Deployments override this (render.yaml sets groq).
ENV LLM_PROVIDER=mock
ENV PYTHONUNBUFFERED=1
EXPOSE 8000

CMD ["sh", "-c", "python -m uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
