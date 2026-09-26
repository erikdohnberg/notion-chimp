# Tracking server image. Sending runs from the CLI, wherever you like.
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir '.[server]'
# Mount or copy your config and templates to /app/config
ENV NOTION_CHIMP_CONFIG=/app/config/config.yaml
EXPOSE 8000
CMD ["gunicorn", "-w", "2", "-b", "0.0.0.0:8000", "notion_chimp.wsgi:app"]
