FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy agent code
COPY resqra_agents/ resqra_agents/
COPY app/ app/

EXPOSE 8001

CMD ["uvicorn", "app.http_server:app", "--host", "0.0.0.0", "--port", "8001"]
