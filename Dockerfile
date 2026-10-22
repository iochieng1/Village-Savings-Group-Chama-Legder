FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CHAMA_DATABASE=/data/chama.db

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY chama ./chama

RUN useradd --create-home app && mkdir /data && chown app /data
USER app
VOLUME ["/data"]
EXPOSE 8000

CMD ["uvicorn", "chama.main:app", "--host", "0.0.0.0", "--port", "8000"]
