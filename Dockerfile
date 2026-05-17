FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN python -m app.rag.ingest

EXPOSE 7860

CMD ["uvicorn", "app.api.server:app", "--host", "0.0.0.0", "--port", "7860"]
