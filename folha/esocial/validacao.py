"""Validação dos XMLs contra os esquemas oficiais (pasta recursos), sem internet."""
from functools import lru_cache
from pathlib import Path

from lxml import etree

RECURSOS = Path(__file__).resolve().parent / "recursos"

ESQUEMAS = {
    "S-1010": "evtTabRubrica.xsd",
    "S-1200": "evtRemun.xsd",
    "S-1210": "evtPgtos.xsd",
    "S-1299": "evtFechaEvPer.xsd",
    "lote": "EnvioLoteEventos-v1_1_1.xsd",
}


@lru_cache(maxsize=None)
def _esquema(arquivo: str) -> etree.XMLSchema:
    return etree.XMLSchema(etree.parse(str(RECURSOS / arquivo)))


def erros(tipo: str, xml: bytes | etree._Element) -> list[str]:
    doc = etree.fromstring(xml) if isinstance(xml, bytes) else xml
    esquema = _esquema(ESQUEMAS[tipo])
    if esquema.validate(doc):
        return []
    return [f"{e.message} (linha {e.line})" for e in esquema.error_log]
