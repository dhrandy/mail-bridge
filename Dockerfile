FROM python:3.12-slim

RUN useradd --create-home --uid 1000 appuser
WORKDIR /app
COPY mail_bridge.py .
USER appuser

EXPOSE 8025
CMD ["python3", "mail_bridge.py"]
