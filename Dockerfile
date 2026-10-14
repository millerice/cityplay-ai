FROM python:3.12-slim
WORKDIR /app
ENV PYTHONPATH=/app/src PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN useradd --create-home --uid 10001 cityplay && mkdir /app/.qloo-private && chown cityplay:cityplay /app/.qloo-private && chmod 700 /app/.qloo-private
COPY src/ ./src/
COPY web/ ./web/
COPY pyproject.toml README.md LICENSE THIRD_PARTY_NOTICES.md ./
USER cityplay
EXPOSE 8787
CMD ["python", "-m", "cityplay.web", "--host", "0.0.0.0"]
