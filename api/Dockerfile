FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
# LibreOffice headless para convertir las plantillas DOCX a PDF conservando el diseño
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       libreoffice-writer fonts-liberation \
    && rm -rf /var/lib/apt/lists/*
ENV SOFFICE_PATH=/usr/bin/soffice
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
