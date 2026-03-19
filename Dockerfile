FROM python:3.11.9-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Dependências do sistema
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Instalação de dependências Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir psycopg2-binary gunicorn whitenoise

# Copia o código do projeto
COPY . .

# --- O AJUSTE ESTÁ AQUI ---
# Coleta os arquivos estáticos (CSS/JS do Admin) para a pasta definida no STATIC_ROOT
# O --noinput evita que o Docker trave pedindo confirmação

EXPOSE 8000

# Substitua o seu CMD atual por este:
CMD ["sh", "-c", "python manage.py collectstatic --noinput && gunicorn hs_money.wsgi:application --bind 0.0.0.0:8000 --workers 3 --timeout 120"]