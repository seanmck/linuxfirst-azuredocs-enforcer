# Dockerfile for Bias Scoring Service
FROM mcr.microsoft.com/devcontainers/python:1-3.12-bullseye

WORKDIR /app

RUN rm -f /etc/apt/sources.list.d/yarn.list

COPY services/bias-scoring-service/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY services/bias-scoring-service/main.py ./
COPY shared ./shared

ENV PYTHONPATH=/app

# List files to debug
RUN ls -la /app/

EXPOSE 9000

CMD ["python", "main.py"]
