FROM python:3.11.9-slim

# Variáveis de ambiente
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Diretório de trabalho
WORKDIR /app

# Dependências do sistema (necessárias para pdfplumber e psycopg2)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Instala dependências Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir psycopg2-binary gunicorn

# Copia o projeto
COPY . .

# Porta padrão do Django
EXPOSE 8000

# Inicia com Gunicorn
CMD ["gunicorn", "hs_money.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3"]
