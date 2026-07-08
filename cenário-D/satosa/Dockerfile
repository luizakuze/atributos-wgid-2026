FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    xmlsec1 \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir SATOSA==8.5.1 gunicorn

WORKDIR /opt/satosa/etc
COPY etc /opt/satosa/etc

ENV SATOSA_CONFIG=/opt/satosa/etc/proxy_conf.yaml
ENV PYTHONPATH=/opt/satosa/etc:/opt/satosa/etc/plugins/microservices

EXPOSE 8000

# wsgi_entrypoint (não satosa.wsgi diretamente) para forçar RSA-SHA256 antes
# de qualquer backend/frontend ser construído - ver wsgi_entrypoint.py
#
# --workers 1 --threads N (não --workers N): o pysaml2 guarda o estado de
# "aguardando resposta a este AuthnRequest" em memória do processo
# (OutstandingQueriesCache). Com múltiplos workers (processos separados), a
# resposta do IdP pode cair num worker diferente do que enviou a
# requisição, e o pysaml2 rejeita como "Unsolicited response" - sem relação
# com quantidade de workers ser pouca, é o oposto: workers demais sem
# estado compartilhado (ex.: Redis) quebra o fluxo. Threads dividem o
# mesmo processo/memória, então resolvem concorrência sem esse problema.
CMD ["gunicorn", "-b", "0.0.0.0:8000", "--worker-class", "gthread", "--workers", "1", "--threads", "4", "wsgi_entrypoint:app"]
