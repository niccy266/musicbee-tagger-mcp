FROM python:3.11-slim AS builder
WORKDIR /app
COPY pyproject.toml mkdocs.yml ./
COPY docs/ docs/
RUN pip install --no-cache-dir mkdocs mkdocs-material mkdocstrings[python] pymdown-extensions
RUN mkdocs build

FROM nginx:alpine
COPY --from=builder /app/site /usr/share/nginx/html
EXPOSE 80
