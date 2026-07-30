FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

RUN addgroup --system gateway && adduser --system --ingroup gateway gateway
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY alembic.ini ./
COPY migrations ./migrations
COPY config ./config
RUN pip install --no-cache-dir .

USER gateway
EXPOSE 8000
CMD ["uvicorn", "gateway.main:app", "--host", "0.0.0.0", "--port", "8000"]
