import base64
import html
import json
import re
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from urllib.parse import urlencode

from flask import Flask, Response, redirect, request, session, url_for
from onelogin.saml2.auth import OneLogin_Saml2_Auth
from onelogin.saml2.settings import OneLogin_Saml2_Settings
from werkzeug.middleware.proxy_fix import ProxyFix

app = Flask(__name__)
app.secret_key = "dev-secret"

app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

BASE_DIR = Path(__file__).resolve().parent

SP_ENTITY_ID = "https://sp-saml.gidlab.rnp.br/saml/metadata"
SP_HOME_URL = "https://sp-saml.gidlab.rnp.br/"
SP_DS_CALLBACK_URL = "https://sp-saml.gidlab.rnp.br/ds/callback"

DISCOVERY_SERVICE_URL = "https://ds2.cafeexpresso.rnp.br/WAYF"

FEDERATION_METADATA_FILE = BASE_DIR / "saml" / "metadata" / "ds-metadata.xml"
SP_CERT_FILE = BASE_DIR / "saml" / "certs" / "sp.crt"
SP_KEY_FILE = BASE_DIR / "saml" / "certs" / "sp.key"

SAML2_HTTP_REDIRECT = "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect"
SAML2_HTTP_POST = "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST"

SCENARIO_LABEL = "Cenário B · Agregação pelo IdP"
SCENARIO_SUBTITLE = "O IdP consulta a Autoridade de Atributos antes de emitir a asserção SAML"
FLOW_STEPS = ["SP", "DS", "IdP", "AA", "IdP", "SP"]
AA_SOURCED_ATTRIBUTES = {"eduPersonEntitlement"}
# A tag "via AA" só é aplicável quando o IdP autenticado é o nosso: só o
# nosso Shibboleth tem o ScriptedAttribute que consulta a AA. IdPs reais
# da federação podem liberar eduPersonEntitlement nativamente, o que não
# tem relação com a AA local.
OWN_IDP_ENTITY_ID = "https://idp-saml.gidlab.rnp.br/idp/shibboleth"

PAGE_STYLE = """
:root {
    --bg: #eff6ff;
    --surface: #ffffff;
    --border: #bfdbfe;
    --text: #0f172a;
    --text-muted: #64748b;
    --primary: #2563eb;
    --primary-hover: #1d4ed8;
    --danger: #dc2626;
    --code-bg: #f8fafc;
    --shadow: 0 1px 2px rgba(15, 23, 42, .04), 0 8px 24px -8px rgba(15, 23, 42, .16);
}

* { box-sizing: border-box; }

body {
    margin: 0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    background: var(--bg);
    color: var(--text);
}

.badge {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    background: rgba(79, 70, 229, .1);
    color: var(--primary);
    font-size: 12px;
    font-weight: 600;
    letter-spacing: .02em;
    padding: 6px 12px;
    border-radius: 999px;
}

.badge-inverted {
    background: rgba(255, 255, 255, .16);
    color: #ffffff;
}

.flow {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 6px;
    margin: 16px 0;
}

.flow-step {
    background: var(--code-bg);
    border: 1px solid var(--border);
    color: var(--text);
    font-size: 13px;
    font-weight: 600;
    padding: 6px 12px;
    border-radius: 8px;
    white-space: nowrap;
}

.flow-arrow {
    color: var(--text-muted);
    font-size: 14px;
}

.card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 14px;
    box-shadow: var(--shadow);
    padding: 24px;
    margin-bottom: 20px;
}

.button {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    background: var(--primary);
    color: white;
    text-decoration: none;
    padding: 12px 20px;
    border-radius: 10px;
    font-weight: 600;
    font-size: 14px;
    transition: background .15s ease;
}

.button:hover { background: var(--primary-hover); }

.button-ghost {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    background: transparent;
    color: var(--danger);
    text-decoration: none;
    padding: 10px 18px;
    border-radius: 10px;
    font-weight: 600;
    font-size: 14px;
    border: 1px solid #fecaca;
    transition: background .15s ease, color .15s ease;
}

.button-ghost:hover { background: var(--danger); color: white; border-color: var(--danger); }

.note { color: var(--text-muted); line-height: 1.6; font-size: 14px; }

.eyebrow {
    text-transform: uppercase;
    letter-spacing: .08em;
    font-size: 11px;
    font-weight: 700;
    color: var(--text-muted);
    margin: 0 0 4px;
}

table { width: 100%; border-collapse: collapse; }

th, td {
    padding: 12px 8px;
    border-bottom: 1px solid var(--border);
    text-align: left;
    vertical-align: top;
    font-size: 14px;
}

th {
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: .05em;
    color: var(--text-muted);
    font-weight: 600;
}

tr:last-child td { border-bottom: none; }

.attribute-name {
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    font-weight: 600;
    font-size: 13px;
    white-space: nowrap;
}

.chip {
    display: inline-block;
    background: var(--code-bg);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 2px 8px;
    font-size: 13px;
    margin: 2px 4px 2px 0;
}

.tag-aa {
    display: inline-block;
    margin-left: 8px;
    font-size: 10px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: .04em;
    color: #7c3aed;
    background: rgba(124, 58, 237, .1);
    padding: 2px 6px;
    border-radius: 999px;
    vertical-align: middle;
}

dl.meta { display: grid; grid-template-columns: 140px 1fr; gap: 8px 16px; margin: 16px 0 0; }
dl.meta dt { color: var(--text-muted); font-size: 12px; text-transform: uppercase; letter-spacing: .04em; }
dl.meta dd {
    margin: 0;
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    font-size: 13px;
    word-break: break-all;
}

details > summary { cursor: pointer; font-weight: 600; font-size: 14px; }

pre {
    background: var(--code-bg);
    border: 1px solid var(--border);
    padding: 16px;
    border-radius: 10px;
    white-space: pre-wrap;
    word-break: break-word;
    font-size: 12px;
    line-height: 1.5;
    margin-top: 12px;
}
"""


def read_cert_body(path):
    lines = Path(path).read_text(encoding="utf-8").splitlines()

    return "".join(
        line.strip()
        for line in lines
        if line.strip()
        and "BEGIN" not in line
        and "END" not in line
    )


def read_key_body(path):
    lines = Path(path).read_text(encoding="utf-8").splitlines()

    return "\n".join(
        line.strip()
        for line in lines
        if line.strip()
        and "BEGIN" not in line
        and "END" not in line
    )


def prepare_flask_request(flask_request):
    forwarded_proto = flask_request.headers.get(
        "X-Forwarded-Proto",
        flask_request.scheme,
    )
    forwarded_host = flask_request.headers.get(
        "X-Forwarded-Host",
        flask_request.host,
    )

    return {
        "https": "on" if forwarded_proto == "https" else "off",
        "http_host": forwarded_host,
        "server_port": "443"
        if forwarded_proto == "https"
        else flask_request.environ.get("SERVER_PORT"),
        "script_name": flask_request.path,
        "get_data": flask_request.args.copy(),
        "post_data": flask_request.form.copy(),
    }


def find_idp_in_federation_metadata(entity_id):
    if not FEDERATION_METADATA_FILE.exists():
        raise RuntimeError(
            f"Federation metadata not found: {FEDERATION_METADATA_FILE}"
        )

    ns = {
        "md": "urn:oasis:names:tc:SAML:2.0:metadata",
        "ds": "http://www.w3.org/2000/09/xmldsig#",
    }

    tree = ET.parse(FEDERATION_METADATA_FILE)
    root = tree.getroot()

    entity = None

    for candidate in root.findall(".//md:EntityDescriptor", ns):
        if candidate.get("entityID") == entity_id:
            entity = candidate
            break

    if entity is None:
        raise RuntimeError(f"IdP not found in federation metadata: {entity_id}")

    idp_descriptor = entity.find("md:IDPSSODescriptor", ns)

    if idp_descriptor is None:
        raise RuntimeError(f"Entity is not an IdP: {entity_id}")

    sso_url = None

    for sso in idp_descriptor.findall("md:SingleSignOnService", ns):
        if sso.get("Binding") == SAML2_HTTP_REDIRECT:
            sso_url = sso.get("Location")
            break

    if not sso_url:
        for sso in idp_descriptor.findall("md:SingleSignOnService", ns):
            sso_url = sso.get("Location")
            break

    if not sso_url:
        raise RuntimeError(f"No SingleSignOnService found for IdP: {entity_id}")

    signing_cert = None

    for key_descriptor in idp_descriptor.findall("md:KeyDescriptor", ns):
        use = key_descriptor.get("use")

        if use not in (None, "signing"):
            continue

        cert = key_descriptor.find(".//ds:X509Certificate", ns)

        if cert is not None and cert.text:
            signing_cert = "".join(cert.text.split())
            break

    if not signing_cert:
        raise RuntimeError(f"No signing certificate found for IdP: {entity_id}")

    return {
        "entity_id": entity_id,
        "sso_url": sso_url,
        "signing_cert": signing_cert,
    }


def build_saml_settings(selected_idp=None):
    sp_cert = read_cert_body(SP_CERT_FILE)
    sp_key = read_key_body(SP_KEY_FILE)

    if selected_idp:
        idp = find_idp_in_federation_metadata(selected_idp)

        idp_settings = {
            "entityId": idp["entity_id"],
            "singleSignOnService": {
                "url": idp["sso_url"],
                "binding": SAML2_HTTP_REDIRECT,
            },
            "singleLogoutService": {
                "url": idp["sso_url"],
                "binding": SAML2_HTTP_REDIRECT,
            },
            "x509cert": idp["signing_cert"],
        }
    else:
        idp_settings = {
            "entityId": "urn:placeholder:idp",
            "singleSignOnService": {
                "url": "https://placeholder.invalid/sso",
                "binding": SAML2_HTTP_REDIRECT,
            },
            "x509cert": "",
        }

    return {
        "strict": False,
        "debug": True,
        "sp": {
            "entityId": SP_ENTITY_ID,
            "assertionConsumerService": {
                "url": "https://sp-saml.gidlab.rnp.br/saml/acs",
                "binding": SAML2_HTTP_POST,
            },
            "singleLogoutService": {
                "url": "https://sp-saml.gidlab.rnp.br/logout",
                "binding": SAML2_HTTP_REDIRECT,
            },
            "NameIDFormat": "urn:oasis:names:tc:SAML:1.1:nameid-format:unspecified",
            "x509cert": sp_cert,
            "privateKey": sp_key,
        },
        "idp": idp_settings,
        "security": {
            "nameIdEncrypted": False,

            "authnRequestsSigned": True,
            "logoutRequestSigned": False,
            "logoutResponseSigned": False,
            "signMetadata": False,

            "wantMessagesSigned": False,
            "wantAssertionsSigned": True,
            "wantAssertionsEncrypted": True,
            "wantNameIdEncrypted": False,

            "wantAttributeStatement": False,

            "requestedAuthnContext": False,
            "validateXML": False,
            "relaxDestinationValidation": True,

            "signatureAlgorithm": "http://www.w3.org/2001/04/xmldsig-more#rsa-sha256",
            "digestAlgorithm": "http://www.w3.org/2001/04/xmlenc#sha256",
        },
        "contactPerson": {
            "technical": {
                "givenName": "GIdLab",
                "emailAddress": "gidlab@rnp.br",
            },
            "support": {
                "givenName": "GIdLab",
                "emailAddress": "gidlab@rnp.br",
            },
        },
        "organization": {
            "pt-BR": {
                "name": "GIdLab",
                "displayname": "GIdLab",
                "url": "https://sp-saml.gidlab.rnp.br",
            }
        },
    }


def init_saml_auth(req, selected_idp=None):
    settings = build_saml_settings(selected_idp)
    return OneLogin_Saml2_Auth(req, old_settings=settings)


def debug_saml_attributes():
    saml_response = request.form.get("SAMLResponse")

    if not saml_response:
        print("\n=== SAML DEBUG ===")
        print("No SAMLResponse found in POST data.")
        return

    try:
        xml = base64.b64decode(saml_response).decode("utf-8")
    except Exception as exception:
        print("\n=== SAML DEBUG ===")
        print(f"Could not decode SAMLResponse: {exception}")
        return

    attribute_names = re.findall(
        r'<(?:\w+:)?Attribute\b[^>]*\bName="([^"]+)"',
        xml,
    )

    counter = Counter(attribute_names)

    print("\n=== SAML ATTRIBUTES RECEIVED FROM IDP/SHIBBOLETH ===")
    if not attribute_names:
        print("No Attribute elements found in SAMLResponse.")
    else:
        for name in attribute_names:
            print(name)

    print("\n=== DUPLICATED SAML ATTRIBUTES ===")
    duplicated = False

    for name, count in sorted(counter.items()):
        if count > 1:
            duplicated = True
            print(f"{name}: {count}")

    if not duplicated:
        print("No duplicated Attribute Name found.")

    print("\n=== END SAML DEBUG ===\n")


def render_flow(steps):
    parts = []

    for index, step in enumerate(steps):
        parts.append(f'<span class="flow-step">{html.escape(step)}</span>')

        if index < len(steps) - 1:
            parts.append('<span class="flow-arrow">&rarr;</span>')

    return f'<div class="flow">{"".join(parts)}</div>'


def render_attribute_value(value):
    if isinstance(value, list):
        if not value:
            return '<span class="note">&mdash;</span>'

        return "".join(
            f'<span class="chip">{html.escape(str(item))}</span>' for item in value
        )

    return html.escape(str(value))


def render_attributes_table(attributes, aa_sourced_attributes=frozenset()):
    preferred_order = [
        "uid",
        "cn",
        "displayName",
        "givenName",
        "sn",
        "mail",
        "eduPersonPrincipalName",
        "eduPersonEntitlement",
        "isMemberOf",
        "role",
    ]

    def render_row(key):
        aa_tag = '<span class="tag-aa">via AA</span>' if key in aa_sourced_attributes else ""

        return f"""
        <tr>
            <td class="attribute-name">{html.escape(key)}{aa_tag}</td>
            <td>{render_attribute_value(attributes[key])}</td>
        </tr>
        """

    rows = ""

    for key in preferred_order:
        if key not in attributes:
            continue

        rows += render_row(key)

    for key in sorted(attributes.keys()):
        if key in preferred_order:
            continue

        rows += render_row(key)

    if not rows:
        rows = """
        <tr>
            <td colspan="2">Nenhum atributo recebido do IdP.</td>
        </tr>
        """

    return rows


@app.route("/")
def index():
    if "samlUserdata" not in session:
        return f"""
        <!doctype html>
        <html lang="pt-BR">
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <title>SP SAML</title>
            <style>{PAGE_STYLE}</style>
        </head>
        <body style="min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 24px;">
            <div class="card" style="max-width: 640px; width: 100%; padding: 40px;">
                <span class="badge">{html.escape(SCENARIO_LABEL)}</span>
                <h1 style="margin: 18px 0 8px; font-size: 26px;">SP SAML</h1>
                <p class="note" style="margin-bottom: 24px;">
                    Na agregação pelo IdP, o IdP consulta a AA, agrega os
                    atributos externos aos institucionais e envia ao SP uma
                    asserção SAML consolidada.
                </p>
                <div style="text-align: center;">
                    <a class="button" href="/login">Entrar</a>
                </div>
            </div>
        </body>
        </html>
        """

    attributes = session.get("samlUserdata", {})
    name_id = session.get("samlNameId", "")
    selected_idp = session.get("selectedIdP", "")

    aa_sourced_attributes = AA_SOURCED_ATTRIBUTES if selected_idp == OWN_IDP_ENTITY_ID else frozenset()
    rows = render_attributes_table(attributes, aa_sourced_attributes)

    return f"""
    <!doctype html>
    <html lang="pt-BR">
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>Atributos SAML recebidos</title>
        <style>{PAGE_STYLE}</style>
    </head>
    <body>
        <header style="background: linear-gradient(135deg, #1d4ed8, #2563eb); color: white; padding: 32px 24px;">
            <div style="max-width: 900px; margin: 0 auto;">
                <span class="badge badge-inverted">{html.escape(SCENARIO_LABEL)}</span>
                <h1 style="margin: 12px 0 4px; font-size: 24px;">Atributos recebidos</h1>
            </div>
        </header>

        <main style="max-width: 900px; margin: 0 auto; padding: 24px;">
            <div class="card">
                <dl class="meta">
                    <dt>SP</dt>
                    <dd>{html.escape(SP_ENTITY_ID)}</dd>
                    <dt>IdP selecionado</dt>
                    <dd>{html.escape(str(selected_idp))}</dd>
                    <dt>NameID</dt>
                    <dd>{html.escape(str(name_id))}</dd>
                </dl>
            </div>

            <div class="card">
                <p class="eyebrow">Atributos</p>
                <table>
                    <thead>
                        <tr>
                            <th>Atributo</th>
                            <th>Valor</th>
                        </tr>
                    </thead>
                    <tbody>
                        {rows}
                    </tbody>
                </table>
            </div>

            <div style="text-align: center;">
                <a class="button-ghost" href="/logout">Sair</a>
            </div>
        </main>
    </body>
    </html>
    """


@app.route("/login")
def login():
    session.clear()

    params = {
        "entityID": SP_ENTITY_ID,
        "return": SP_DS_CALLBACK_URL,
        "returnIDParam": "entityID",
    }

    discovery_url = f"{DISCOVERY_SERVICE_URL}?{urlencode(params)}"

    print("\n=== DISCOVERY SERVICE URL ===")
    print(discovery_url)
    print("=== END DISCOVERY SERVICE URL ===\n")

    return redirect(discovery_url)


@app.route("/ds/callback")
def ds_callback():
    selected_idp = request.args.get("entityID")

    print("\n=== DISCOVERY SERVICE CALLBACK ===")
    print(f"Selected IdP: {selected_idp}")
    print("=== END DISCOVERY SERVICE CALLBACK ===\n")

    if not selected_idp:
        return "Discovery Service não retornou entityID do IdP.", 400

    try:
        idp = find_idp_in_federation_metadata(selected_idp)
    except Exception as exception:
        return f"IdP não encontrado no metadata federado: {html.escape(str(exception))}", 400

    session["selectedIdP"] = selected_idp

    print("\n=== IDP LOADED FROM FEDERATION METADATA ===")
    print(f"EntityID: {idp['entity_id']}")
    print(f"SSO URL: {idp['sso_url']}")
    print(f"Signing cert length: {len(idp['signing_cert'])}")
    print("=== END IDP LOADED FROM FEDERATION METADATA ===\n")

    req = prepare_flask_request(request)
    auth = init_saml_auth(req, selected_idp)

    login_url = auth.login(return_to=SP_HOME_URL)

    print("\n=== SAML LOGIN URL AFTER DS ===")
    print(login_url)
    print("=== END SAML LOGIN URL AFTER DS ===\n")

    return redirect(login_url)


@app.route("/saml/acs", methods=["POST"])
def acs():
    selected_idp = session.get("selectedIdP")

    if not selected_idp:
        return "Sessão não contém selectedIdP. Inicie novamente em /login.", 400

    req = prepare_flask_request(request)
    auth = init_saml_auth(req, selected_idp)

    debug_saml_attributes()

    auth.process_response()
    errors = auth.get_errors()

    if errors:
        error_reason = auth.get_last_error_reason() or ""
        return f"""
        <!doctype html>
        <html lang="pt-BR">
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <title>Erro SAML</title>
            <style>{PAGE_STYLE}</style>
        </head>
        <body style="min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 24px;">
            <div class="card" style="max-width: 640px; width: 100%; padding: 40px;">
                <span class="badge" style="background: rgba(220, 38, 38, .1); color: var(--danger);">Erro SAML</span>
                <h1 style="margin: 18px 0 8px; font-size: 22px;">Não foi possível concluir o login</h1>
                <p class="note">{html.escape(str(errors))}</p>
                <pre>{html.escape(error_reason)}</pre>
                <a class="button" href="/login" style="margin-top: 16px;">Tentar novamente</a>
            </div>
        </body>
        </html>
        """, 400

    if not auth.is_authenticated():
        return "Usuário não autenticado.", 401

    # get_attributes() usa o atributo XML "Name" (o OID); usamos
    # "FriendlyName" (ex.: "uid", "cn") para exibição e para casar com os
    # nomes que o attribute-resolver.xml do IdP já declara.
    saml_attributes = auth.get_friendlyname_attributes()
    name_id = auth.get_nameid()

    session["samlUserdata"] = saml_attributes
    session["samlNameId"] = name_id
    session["selectedIdP"] = selected_idp

    print("\n=== ATTRIBUTES RECEIVED FROM IDP/SHIBBOLETH ===")
    print(json.dumps(saml_attributes, indent=2, ensure_ascii=False))
    print("=== END ATTRIBUTES RECEIVED FROM IDP/SHIBBOLETH ===\n")

    return redirect(url_for("index"))


@app.route("/saml/metadata")
def metadata():
    settings = build_saml_settings()
    saml_settings = OneLogin_Saml2_Settings(settings, sp_validation_only=True)

    metadata_xml = saml_settings.get_sp_metadata()
    errors = saml_settings.validate_metadata(metadata_xml)

    if errors:
        print("Errors validating the metadata:")
        for error in errors:
            print(error)
        return Response(", ".join(errors), status=500)

    try:
        root = ET.fromstring(metadata_xml)

        if 'validUntil' in root.attrib:
            del root.attrib['validUntil']
        if 'cacheDuration' in root.attrib:
            del root.attrib['cacheDuration']

        metadata_xml = ET.tostring(root, encoding="utf-8")
    except Exception as e:
        print(f"Erro ao limpar atributos do metadado: {e}")
        pass

    return Response(metadata_xml, mimetype="text/xml")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)