# Imagem de produção do sistema de Prospecção de Parceiros
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONIOENCODING=utf-8 \
    AMBIENTE=producao HOST=0.0.0.0 PORTA=8001 PP_PASTA_DADOS=/dados

WORKDIR /app
COPY requirements.txt requirements-producao.txt ./
RUN pip install --no-cache-dir -r requirements-producao.txt
COPY app ./app
COPY iniciar.py redefinir_senha.py importar_receita.py ./

RUN useradd --create-home sistema && mkdir -p /dados && chown sistema /dados
USER sistema
VOLUME ["/dados"]
EXPOSE 8001
HEALTHCHECK CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8001/api/saude')"
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001", "--proxy-headers", "--forwarded-allow-ips", "*"]
