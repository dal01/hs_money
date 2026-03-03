from django.urls import path
from . import views

app_name = 'cartao_credito'

urlpatterns = [
    path('', views.index, name='index'),
    path('import-web/', views.import_pdf_web, name='import_pdf_web'),
]
