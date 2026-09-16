FROM python:3.14-slim
WORKDIR /app
COPY pyproject.toml /app/
COPY src /app/src
RUN pip install --no-cache-dir fastapi 'uvicorn[standard]' pydantic
ENV PYTHONPATH=/app/src
EXPOSE 8000
CMD ["uvicorn","ra_agent_studio.api:app","--host","0.0.0.0","--port","8000"]