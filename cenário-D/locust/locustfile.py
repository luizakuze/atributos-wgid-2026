from locust import HttpUser, task, between, events
from urllib.parse import urljoin
import urllib3
import requests
import re
import html
import time
import os
import base64
import gevent


urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Descarta os primeiros WARMUP_SECONDS de medicoes (cold start do JVM
# do shib-idp e pool de conexoes) antes de comecar a medicao real.
WARMUP_SECONDS = int(os.getenv("LOCUST_WARMUP_SECONDS", "15"))

# Numero alvo de execucoes pos-warmup; ao atingir, encerra a rodada
# sozinha. 0 desativa (roda so por --run-time).
TARGET_ITERATIONS = int(os.getenv("LOCUST_TARGET_ITERATIONS", "0"))

_warmup_done = False
_completed_count = 0

# DS externo (ds2.cafeexpresso.rnp.br) e intermitente; timeout maior
# evita falso negativo. Nao afeta a metrica CUSTO, medida a partir da
# etapa seguinte.
DS_TIMEOUT = int(os.getenv("LOCUST_DS_TIMEOUT", "60"))
DS_MAX_RETRIES = int(os.getenv("LOCUST_DS_MAX_RETRIES", "2"))
DS_RETRY_BACKOFF_SECONDS = 2


def request_with_retry(request_func, *args, **kwargs):
    attempt = 0

    while True:
        try:
            return request_func(*args, **kwargs)
        except requests.exceptions.RequestException:
            if attempt >= DS_MAX_RETRIES:
                raise

            attempt += 1
            time.sleep(DS_RETRY_BACKOFF_SECONDS)


@events.test_start.add_listener
def _descartar_warmup(environment, **kwargs):
    def _reset():
        global _warmup_done
        environment.stats.reset_all()
        _warmup_done = True
        print(f"[warmup] {WARMUP_SECONDS}s concluidos - estatisticas zeradas, medicao real comecando agora")

    gevent.spawn_later(WARMUP_SECONDS, _reset)


def _register_completion(environment):
    global _completed_count

    if not _warmup_done:
        return

    _completed_count += 1

    if TARGET_ITERATIONS and _completed_count >= TARGET_ITERATIONS:
        # spawn evita deadlock: quit() direto bloquearia esperando a
        # propria greenlet atual, que so termina apos retornar daqui.
        gevent.spawn(environment.runner.quit)

USERNAME = os.getenv("SAML_USER", "bob")
PASSWORD = os.getenv("SAML_PASS", "bob")

IDP_ENTITY_ID = os.getenv(
    "IDP_ENTITY_ID",
    "https://idp-saml.gidlab.rnp.br/idp/shibboleth"
)

AA_URL = os.getenv(
    "AA_URL",
    "https://aa-api.gidlab.rnp.br/attributes/bob"
)


def fire_custom(environment, name, response_time, response_length=0, exception=None):
    environment.events.request.fire(
        request_type="CUSTOM",
        name=name,
        response_time=response_time,
        response_length=response_length,
        exception=exception,
        context={}
    )


def clean_text(value):
    return html.unescape(value).strip() if value else ""


def get_first_link_matching(page, patterns):
    links = re.findall(
        r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
        page,
        re.I | re.S
    )

    for href, label in links:
        label_clean = re.sub(r"<[^>]+>", "", label)
        label_clean = clean_text(label_clean)

        for pattern in patterns:
            if pattern.lower() in href.lower() or pattern.lower() in label_clean.lower():
                return clean_text(href)

    return None


def get_all_forms(page):
    return re.findall(r'<form.*?</form>', page, re.I | re.S)


def get_form_action(form_html):
    match = re.search(r'<form[^>]+action=["\']([^"\']+)["\']', form_html, re.I)
    return clean_text(match.group(1)) if match else None


def get_form_method(form_html):
    match = re.search(r'<form[^>]+method=["\']([^"\']+)["\']', form_html, re.I)
    return clean_text(match.group(1)).lower() if match else "post"


def get_inputs(form_html):
    data = {}

    for match in re.finditer(r'<input[^>]*>', form_html, re.I):
        tag = match.group(0)

        name_match = re.search(r'name=["\']([^"\']+)["\']', tag, re.I)
        if not name_match:
            continue

        value_match = re.search(r'value=["\']([^"\']*)["\']', tag, re.I)

        name = clean_text(name_match.group(1))
        value = clean_text(value_match.group(1)) if value_match else ""

        data[name] = value

    return data


def find_ds_form(page):
    forms = get_all_forms(page)
    return forms[0] if forms else None


def fill_ds_data(ds_form):
    data = get_inputs(ds_form)

    possible_fields = [
        "entityID",
        "user_idp",
        "idp",
        "origin",
        "selected_idp",
        "shib_idp_ls_value",
        "IdP",
        "idpentityid",
    ]

    for field in possible_fields:
        data[field] = IDP_ENTITY_ID

    return data


def find_login_form(page):
    for form in get_all_forms(page):
        lower = form.lower()

        if (
            "j_username" in lower
            or "j_password" in lower
            or "username" in lower
            or "password" in lower
        ):
            return form

    return None


def find_saml_form(page):
    forms = get_all_forms(page)

    for form in forms:
        lower = form.lower()
        data = get_inputs(form)

        if "samlresponse" in lower or "SAMLResponse" in data:
            return form

    return None


def find_redirect_url(page):
    patterns = [
        r'window\.location\.href\s*=\s*["\']([^"\']+)["\']',
        r'window\.location\s*=\s*["\']([^"\']+)["\']',
        r'location\.href\s*=\s*["\']([^"\']+)["\']',
        r'location\.replace\(["\']([^"\']+)["\']\)',
        r'<meta[^>]+http-equiv=["\']refresh["\'][^>]+content=["\'][^;]+;\s*url=([^"\']+)["\']',
    ]

    for pattern in patterns:
        match = re.search(pattern, page, re.I)

        if match:
            return clean_text(match.group(1))

    return None


def get_saml_response_size_bytes(saml_data):
    saml_response = saml_data.get("SAMLResponse")

    if not saml_response:
        return 0

    missing_padding = len(saml_response) % 4

    if missing_padding:
        saml_response += "=" * (4 - missing_padding)

    decoded = base64.b64decode(saml_response)

    return len(decoded)


def debug_page(label, response):
    print("=" * 80)
    print(label)
    print("URL:", response.url)
    print("STATUS:", response.status_code)
    print("HEADERS:", dict(response.headers))
    print("HTML:")
    print(response.text[:4000])
    print("=" * 80)


class SAMLAgregacaoProxyUser(HttpUser):
    """
    Cenario D - Agregacao pelo proxy de identidade (Figura 1d do artigo).
    O proxy (SATOSA) concentra a autenticacao federada: recebe o usuario
    do DS, redireciona ao IdP de origem, recebe a assercao com os
    atributos institucionais, consulta a AA para os atributos
    complementares, agrega tudo e so entao entrega a asserção final ao
    SP. Fluxo com 9 mensagens (Tabela 1).

    Mensagens 3 e 4 (DS direciona ao proxy / proxy redireciona ao IdP)
    acontecem dentro da mesma cadeia de redirecionamentos HTTP e sao
    seguidas automaticamente pelo cliente, por isso sao reportadas como
    uma unica medicao. O mesmo vale para as mensagens 6 e 7 (proxy
    consulta a AA / AA responde), que acontecem dentro do proprio
    processamento do POST ao ACS do proxy e sao isoladas com uma
    chamada direta equivalente, na mesma tecnica ja usada nos cenarios
    B e C.
    """

    wait_time = between(1, 3)

    def on_start(self):
        self.base_url = self.host.rstrip("/")

    @task
    def fluxo_agregacao_proxy_1_a_9(self):
        session = requests.Session()
        session.verify = False

        total_start = time.time()

        try:
            step_start = time.time()

            r1 = session.get(
                f"{self.base_url}/",
                allow_redirects=True,
                timeout=20
            )

            step_ms = (time.time() - step_start) * 1000

            fire_custom(
                self.environment,
                "1 - Usuario solicita acesso ao SP",
                step_ms,
                len(r1.content or b""),
                None if r1.ok else Exception(f"HTTP {r1.status_code}")
            )

            if not r1.ok:
                debug_page("Falha no passo 1", r1)
                return

            login_href = get_first_link_matching(
                r1.text,
                [
                    "Login via Federação",
                    "Login via Federacao",
                    "login",
                    "federação",
                    "federacao"
                ]
            )

            if not login_href:
                print("Nao encontrou link de login na pagina inicial.")
                print(r1.text[:3000])
                return

            login_url = urljoin(r1.url, login_href)

            step_start = time.time()

            r2 = session.get(
                login_url,
                allow_redirects=False,
                timeout=20
            )

            step_ms = (time.time() - step_start) * 1000

            fire_custom(
                self.environment,
                "2 - SP encaminha a solicitacao ao DS",
                step_ms,
                len(r2.content or b""),
                None if r2.status_code in [301, 302, 303, 307, 308]
                else Exception(f"HTTP {r2.status_code}")
            )

            if r2.status_code not in [301, 302, 303, 307, 308]:
                debug_page("Falha no passo 2", r2)
                return

            ds_url = urljoin(r2.url, r2.headers.get("Location"))

            step_start = time.time()

            r3 = request_with_retry(
                session.get,
                ds_url,
                allow_redirects=True,
                timeout=DS_TIMEOUT
            )

            ds_form = find_ds_form(r3.text)

            if not ds_form:
                step_ms = (time.time() - step_start) * 1000

                fire_custom(
                    self.environment,
                    "3/4 - DS direciona ao proxy e proxy redireciona ao IdP",
                    step_ms,
                    len(r3.content or b""),
                    Exception("Formulario do DS nao encontrado")
                )

                debug_page("Falha no passo 3/4 - formulario DS nao encontrado", r3)
                return

            ds_action = get_form_action(ds_form) or r3.url
            ds_method = get_form_method(ds_form)
            ds_data = fill_ds_data(ds_form)
            ds_submit_url = urljoin(r3.url, ds_action)

            if ds_method == "get":
                r3b = request_with_retry(
                    session.get,
                    ds_submit_url,
                    params=ds_data,
                    allow_redirects=True,
                    timeout=DS_TIMEOUT
                )
            else:
                r3b = request_with_retry(
                    session.post,
                    ds_submit_url,
                    data=ds_data,
                    allow_redirects=True,
                    timeout=DS_TIMEOUT
                )

            redirect_url = find_redirect_url(r3b.text)

            if redirect_url:
                redirect_url = urljoin(r3b.url, redirect_url)

                r3b = request_with_retry(
                    session.get,
                    redirect_url,
                    allow_redirects=True,
                    timeout=DS_TIMEOUT
                )

            step_ms = (time.time() - step_start) * 1000
            login_form = find_login_form(r3b.text)

            fire_custom(
                self.environment,
                "3/4 - DS direciona ao proxy e proxy redireciona ao IdP",
                step_ms,
                len(r3b.content or b""),
                None if login_form else Exception("Tela de login do IdP nao encontrada")
            )

            if not login_form:
                debug_page("Falha no passo 3/4 - tela de login nao encontrada", r3b)
                return

            # mensagem 4 (proxy->IdP) nao e isolavel do lado do cliente
            # (mesma cadeia de redirect do passo anterior), entao a
            # metrica CUSTO comeca aqui, na mensagem 5
            msg5_start = time.time()
            step_start = msg5_start

            login_action = get_form_action(login_form)
            login_data = get_inputs(login_form)

            login_data["j_username"] = USERNAME
            login_data["j_password"] = PASSWORD
            login_data["_eventId_proceed"] = "Login"

            # Evita marcar checkbox opcional
            login_data.pop("donotcache", None)
            login_data.pop("_shib_idp_revokeConsent", None)

            # Compatibilidade caso o IdP use nomes genericos
            login_data["username"] = USERNAME
            login_data["password"] = PASSWORD

            login_post_url = urljoin(r3b.url, login_action)

            r5 = session.post(
                login_post_url,
                data=login_data,
                allow_redirects=True,
                timeout=20
            )

            step_ms = (time.time() - step_start) * 1000

            voltou_para_login = (
                "j_username" in r5.text
                and "j_password" in r5.text
                and "Web Login Service" in r5.text
            )

            saml_form_to_proxy = find_saml_form(r5.text)

            fire_custom(
                self.environment,
                "5 - IdP autentica o usuario e envia ao proxy a assercao",
                step_ms,
                len(r5.content or b""),
                None if r5.ok and not voltou_para_login and saml_form_to_proxy
                else Exception("Login no IdP falhou ou assercao para o proxy nao encontrada")
            )

            if not r5.ok or voltou_para_login or not saml_form_to_proxy:
                debug_page("Falha no passo 5 - login nao autenticou", r5)
                return

            step_start = time.time()
            aa_exception = None
            aa_len = 0

            try:
                r_aa = requests.get(
                    AA_URL,
                    verify=False,
                    timeout=20
                )

                aa_len = len(r_aa.content or b"")

                if not r_aa.ok:
                    aa_exception = Exception(f"AA HTTP {r_aa.status_code}")

            except Exception as exc:
                aa_exception = exc

            step_ms = (time.time() - step_start) * 1000

            fire_custom(
                self.environment,
                "6/7 - Proxy consulta a AA e recebe os atributos complementares",
                step_ms,
                aa_len,
                aa_exception
            )

            step_start = time.time()

            saml_action_1 = get_form_action(saml_form_to_proxy)
            saml_data_1 = get_inputs(saml_form_to_proxy)

            if "SAMLResponse" not in saml_data_1:
                step_ms = (time.time() - step_start) * 1000

                fire_custom(
                    self.environment,
                    "8 - Proxy agrega os atributos e constroi a resposta consolidada",
                    step_ms,
                    0,
                    Exception("Campo SAMLResponse (IdP -> proxy) nao encontrado")
                )

                print("Formulario IdP->proxy encontrado, mas sem campo SAMLResponse:")
                print(saml_form_to_proxy[:3000])
                return

            proxy_acs_url = urljoin(r5.url, saml_action_1)

            r8 = session.post(
                proxy_acs_url,
                data=saml_data_1,
                allow_redirects=True,
                timeout=20
            )

            saml_form_to_sp = find_saml_form(r8.text)

            step_ms = (time.time() - step_start) * 1000

            fire_custom(
                self.environment,
                "8 - Proxy agrega os atributos e constroi a resposta consolidada",
                step_ms,
                len(r8.content or b""),
                None if r8.ok and saml_form_to_sp
                else Exception("Resposta consolidada do proxy para o SP nao encontrada")
            )

            if not r8.ok or not saml_form_to_sp:
                debug_page("Falha no passo 8 - resposta do proxy", r8)
                return

            step_start = time.time()

            saml_action_2 = get_form_action(saml_form_to_sp)
            saml_data_2 = get_inputs(saml_form_to_sp)

            if "SAMLResponse" not in saml_data_2:
                step_ms = (time.time() - step_start) * 1000

                fire_custom(
                    self.environment,
                    "9 - SP recebe os atributos agregados e decide o acesso",
                    step_ms,
                    0,
                    Exception("Campo SAMLResponse (proxy -> SP) nao encontrado")
                )

                print("Formulario proxy->SP encontrado, mas sem campo SAMLResponse:")
                print(saml_form_to_sp[:3000])
                return

            saml_response_size_bytes = get_saml_response_size_bytes(saml_data_2)

            fire_custom(
                self.environment,
                "Tamanho da assercao SAML em bytes",
                0,
                saml_response_size_bytes,
                None
            )

            sp_acs_url = urljoin(r8.url, saml_action_2)

            r9 = session.post(
                sp_acs_url,
                data=saml_data_2,
                allow_redirects=True,
                timeout=20
            )

            step_ms = (time.time() - step_start) * 1000

            final_ok = (
                "Atributos recebidos" in r9.text
                or "SP SAML Demo" in r9.text
                or "IdP selecionado" in r9.text
            )

            fire_custom(
                self.environment,
                "9 - SP recebe os atributos agregados e decide o acesso",
                step_ms,
                len(r9.content or b""),
                None if r9.ok and final_ok else Exception(f"HTTP {r9.status_code}")
            )

            if not r9.ok or not final_ok:
                debug_page("Falha no passo 9 - SP nao confirmou o acesso", r9)
                return

            # soma real por amostra, nao soma de medianas de etapas
            custo_ms = (time.time() - msg5_start) * 1000

            fire_custom(
                self.environment,
                "CUSTO - Mensagem 5 ao final (medido direto)",
                custo_ms,
                len(r9.content or b""),
                None
            )

            _register_completion(self.environment)

            total_ms = (time.time() - total_start) * 1000

            fire_custom(
                self.environment,
                "TOTAL - Fluxo completo",
                total_ms,
                len(r9.content or b""),
                None
            )

            print("LOGIN OK - fluxo 1 a 9 completo")
            print("Tempo total ms:", total_ms)
            print("Tamanho SAMLResponse decodificada bytes (proxy->SP):", saml_response_size_bytes)

        except Exception as exc:
            total_ms = (time.time() - total_start) * 1000

            fire_custom(
                self.environment,
                "TOTAL - Fluxo completo",
                total_ms,
                0,
                exc
            )

            print("Erro geral no fluxo:", repr(exc))
