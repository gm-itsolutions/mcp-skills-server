FROM python:3.11-slim

WORKDIR /app

# System-Dependencies für PDF-Verarbeitung
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    # Für pdf2image (poppler)
    poppler-utils \
    # Für Schriftarten in reportlab
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# Python Dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Source Code
COPY src/ ./src/

# Erstelle Verzeichnisse
RUN mkdir -p /app/skills-data /app/files

# Skills kopieren (werden durch Volume überschrieben)
COPY skills-data/ ./skills-data/

# Umgebungsvariablen
ENV SKILLS_DIR=/app/skills-data
ENV FILES_DIR=/app/files
ENV PORT=8001
ENV HOST=0.0.0.0
ENV PYTHONUNBUFFERED=1

EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8001/health || exit 1

CMD ["python", "src/server.py"]
