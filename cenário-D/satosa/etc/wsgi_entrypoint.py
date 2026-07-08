"""
Ponto de entrada WSGI usado no lugar de satosa.wsgi:app diretamente.

O pysaml2 usa um singleton (DefaultSignature) para decidir o algoritmo de
assinatura padrão quando `signing_algorithm`/`digest_algorithm` não são
resolvidos a partir da config (o que acontece sempre para SPConfig/IdPConfig,
já que Entity.__init__ consulta `config.getattr("signing_algorithm")` sem
contexto explícito, e esse valor nunca é promovido para `_sp_...`/`_idp_...`
mesmo quando declarado no YAML). O default embutido é RSA-SHA1, que o
Shibboleth real deste laboratório rejeita ("Message Security Error").

Este módulo precisa ser importado (e o singleton inicializado) ANTES de
`satosa.wsgi` construir os backends/frontends - por isso é o alvo do
gunicorn no lugar de satosa.wsgi:app.
"""

from saml2.xmldsig import DefaultSignature, SIG_RSA_SHA256, DIGEST_SHA256

DefaultSignature(sign_alg=SIG_RSA_SHA256, digest_alg=DIGEST_SHA256)

from satosa.wsgi import app  # noqa: E402,F401
