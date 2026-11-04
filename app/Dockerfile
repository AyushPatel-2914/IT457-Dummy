FROM python:3.12-slim
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY src ./src
ENV SERVICE=monolith PORT=5000 WORKERS=2 THREADS=4 PYTHONUNBUFFERED=1
EXPOSE 5000
CMD gunicorn --workers $WORKERS --threads $THREADS --bind 0.0.0.0:$PORT --timeout 30 "src.main:create_app()"
