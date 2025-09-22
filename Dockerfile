FROM python:3.13.5

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --upgrade pip && pip install --no-cache-dir -r requirements.txt

COPY . .

# EXPOSE 8000
# CMD ["daphne", "-b", "0.0.0.0", "-p", "8000", "config.asgi:application"]