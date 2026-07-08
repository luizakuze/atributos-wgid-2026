import logging

import requests
from satosa.micro_services.base import ResponseMicroService

logger = logging.getLogger(__name__)


class AaAttributeAggregation(ResponseMicroService):
    """
    Cenário D: agregação pelo proxy. Depois que o proxy recebe a
    asserção do IdP real (identidade + atributos institucionais
    básicos), consulta a Autoridade de Atributos (AA) para obter
    atributos complementares (ex.: eduPersonEntitlement) e agrega-os
    antes de repassar a resposta final ao SP.
    """

    def __init__(self, config, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.aa_base_url = config["aa_base_url"]
        self.timeout_seconds = config.get("timeout_seconds", 3)
        self.user_id_attribute = config.get("user_id_attribute", "uid")
        self.target_attribute = config.get("target_attribute", "edupersonentitlement")
        self.source_attribute = config.get("source_attribute", "eduPersonEntitlement")

    def process(self, context, data):
        user_id_values = data.attributes.get(self.user_id_attribute) or []
        user_id = user_id_values[0] if user_id_values else None

        if user_id:
            aa_attributes = self._fetch_aa_attributes(user_id)

            if self.source_attribute in aa_attributes:
                data.attributes[self.target_attribute] = aa_attributes[self.source_attribute]

        return super().process(context, data)

    def _fetch_aa_attributes(self, user_id):
        url = f"{self.aa_base_url}/attributes/{user_id}"

        try:
            response = requests.get(url, timeout=self.timeout_seconds)
        except requests.RequestException as exception:
            logger.warning("Falha ao consultar a AA (%s): %s", url, exception)
            return {}

        if response.status_code == 404:
            logger.info("AA não possui atributos para o usuário: %s", user_id)
            return {}

        if not response.ok:
            logger.warning("AA retornou HTTP %s para %s", response.status_code, url)
            return {}

        return response.json()
