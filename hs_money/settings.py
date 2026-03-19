import os
import environ
from pathlib import Path
from django.contrib.messages import constants as message_constants

# 1. Caminhos Base
BASE_DIR = Path(__file__).resolve().parent.parent

# 2. Configuração de Ambiente
env = environ.Env(
    DEBUG=(bool, False)
)
# Tenta ler o .env local (não afeta o Docker, que usa variáveis da Stack)
environ.Env.read_env(os.path.join(BASE_DIR, '.env'))

# 3. Segurança e Debug
# No PC local, se não houver SECRET_KEY no .env, ele usa a de backup
SECRET_KEY = env('SECRET_KEY', default='django-insecure-local-dev-key-123')
DEBUG = env('DEBUG', default=True)
ALLOWED_HOSTS = env.list('ALLOWED_HOSTS', default=['*'])

# 4. Definição do App
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # Seus Apps
    'hs_money.core.apps.CoreConfig',
    'hs_money.cartao_credito.apps.CartaoCreditoConfig',
    'hs_money.conta_corrente.apps.ContaCorrenteConfig',
    'hs_money.relatorios.apps.RelatoriosConfig',
    'hs_money.investimentos.apps.InvestimentosConfig',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',  # Essencial para CSS no Docker
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'hs_money.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'hs_money.wsgi.application'

# 5. Banco de Dados Híbrido
# Se DATABASE_URL existir (Docker), usa Postgres. Caso contrário, usa SQLite local.
DATABASES = {
    'default': env.db('DATABASE_URL', default=f'sqlite:///{BASE_DIR / "db.sqlite3"}')
}

# 6. Arquivos Estáticos e WhiteNoise (Django 5.1+)
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        # 'StaticFilesStorage' é mais seguro para evitar erros de 
        # 'Missing Manifest' se o collectstatic falhar parcialmente
        "BACKEND": "whitenoise.storage.StaticFilesStorage",
    },
}

WHITENOISE_USE_FINDERS = True

# 7. Internacionalização
LANGUAGE_CODE = 'pt-br'
TIME_ZONE = 'America/Sao_Paulo'
USE_I18N = True
USE_TZ = True

# 8. Outras Configurações
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
DADOS_DIR = BASE_DIR / "data"

# Mapeamento de Mensagens para Bootstrap
MESSAGE_TAGS = {
    message_constants.ERROR: 'danger',
}