#!/usr/bin/env bash
# Sobe cada cenario, roda a carga do Locust (headless) e derruba antes do
# proximo - so um cenario fica de pe por vez. Gera os CSVs em
# cenário-X/locust/resultados_x_clean_*.csv.
#
# Uso:
#   ./run_all_locust.sh            # roda A, B, C, D nessa ordem
#   ./run_all_locust.sh B D        # roda so os cenarios passados, na ordem dada
#
# Requer /etc/hosts (ou DNS local) resolvendo idp-saml.gidlab.rnp.br,
# sp-saml.gidlab.rnp.br e, para o cenario D, proxy-wgid.gidlab.rnp.br para 127.0.0.1.

set -euo pipefail

HOST_URL="https://sp-saml.gidlab.rnp.br"
IDP_METADATA_URL="https://idp-saml.gidlab.rnp.br/idp/shibboleth"
USERS=3
SPAWN_RATE=3
TARGET_ITERATIONS=100 # N alvo de execucoes por cenario
RUN_TIME="600s"        # teto de seguranca; a rodada para sozinha ao atingir TARGET_ITERATIONS
STARTUP_TIMEOUT=240    # segundos esperando cada endpoint responder 200
READY_EXTRA_WAIT=10    # margem apos o IdP responder, antes de iniciar a carga
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

SCENARIOS=("$@")
if [ "${#SCENARIOS[@]}" -eq 0 ]; then
    SCENARIOS=(A B C D)
fi

# curl sem --fail nao detecta 502/503; checa o status HTTP explicitamente.
wait_for_http_200() {
    local url="$1"
    local label="$2"
    local elapsed=0
    local code

    echo "Aguardando $label ($url) responder 200..."

    while true; do
        code=$(curl -k -s -o /dev/null -w '%{http_code}' --max-time 5 "$url" || echo "000")

        if [ "$code" = "200" ]; then
            echo "$label pronto depois de ${elapsed}s."
            return 0
        fi

        sleep 3
        elapsed=$((elapsed + 3))

        if [ "$elapsed" -ge "$STARTUP_TIMEOUT" ]; then
            echo "Timeout esperando $label subir (${STARTUP_TIMEOUT}s), ultimo status: $code" >&2
            return 1
        fi
    done
}

wait_for_ready() {
    wait_for_http_200 "$HOST_URL/" "SP"
    wait_for_http_200 "$IDP_METADATA_URL" "IdP"

    echo "Aguardando mais ${READY_EXTRA_WAIT}s de margem antes de iniciar a carga..."
    sleep "$READY_EXTRA_WAIT"
}

run_scenario() {
    local scenario="$1"
    local lower dir

    lower=$(echo "$scenario" | tr '[:upper:]' '[:lower:]')
    dir="$REPO_ROOT/cenário-$scenario"

    if [ ! -d "$dir" ]; then
        echo "Cenario '$scenario' nao encontrado em $dir" >&2
        return 1
    fi

    cd "$dir"
    trap 'echo "-> docker compose down (cenario '"$scenario"')"; docker compose down' EXIT

    echo "=============================================="
    echo "Cenario $scenario"
    echo "=============================================="

    echo "-> docker compose up --build -d"
    docker compose up --build -d

    wait_for_ready

    cd locust

    echo "-> locust (headless, ${USERS} usuarios, N alvo=${TARGET_ITERATIONS}, teto=${RUN_TIME})"
    LOCUST_TARGET_ITERATIONS="$TARGET_ITERATIONS" \
    locust -f locustfile.py --host "$HOST_URL" \
        --headless --users "$USERS" --spawn-rate "$SPAWN_RATE" --run-time "$RUN_TIME" \
        --csv="resultados_${lower}_clean" --csv-full-history

    echo "Cenario $scenario concluido. CSVs em cenário-$scenario/locust/resultados_${lower}_clean_*.csv"
    echo
}

for scenario in "${SCENARIOS[@]}"; do
    ( run_scenario "$scenario" )
done

echo "Todos os cenarios pedidos foram executados."
