FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir -e '.[dev]'
COPY tests ./tests
COPY data ./data

ENTRYPOINT ["python", "-m", "translation_agent"]
CMD ["run", "--repeat", "2"]
