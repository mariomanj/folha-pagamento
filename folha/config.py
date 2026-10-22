"""Pasta de dados e tabelas editáveis (tabelas.json).

O executável não pode ser editado, então as tabelas legais e os parâmetros da
empresa ficam num JSON na pasta de dados. Na primeira execução o arquivo é
criado com os valores padrão de tabelas.py.
"""
import json
import os
import sys
from decimal import Decimal as D
from pathlib import Path

from . import tabelas

ARQUIVO_TABELAS = "tabelas.json"
DERIVADAS = {"FATOR_HORA_NOTURNA"}  # calculadas, não editáveis


def pasta_dados() -> Path:
    """FOLHA_DADOS, se definida; no executável, Documentos\\FolhaPagamento;
    rodando do código-fonte, a pasta do projeto."""
    if pasta := os.environ.get("FOLHA_DADOS"):
        p = Path(pasta)
    elif getattr(sys, "frozen", False):
        p = Path.home() / "Documents" / "FolhaPagamento"
    else:
        p = Path(__file__).resolve().parent.parent
    p.mkdir(parents=True, exist_ok=True)
    return p


def _nomes() -> list[str]:
    return [n for n, v in vars(tabelas).items()
            if n.isupper() and n not in DERIVADAS and not isinstance(v, type)]


def _para_json(v):
    if isinstance(v, D):
        return str(v)
    if isinstance(v, (list, tuple)):
        return [_para_json(x) for x in v]
    if isinstance(v, dict):
        return {k: _para_json(x) for k, x in v.items()}
    return v


def _do_json(modelo, v):
    """Converte `v` para o mesmo tipo do valor padrão `modelo`."""
    if v is None:
        return None
    if isinstance(modelo, bool):
        return bool(v)
    if isinstance(modelo, D):
        return D(str(v))
    if isinstance(modelo, int):
        return int(v)
    if isinstance(modelo, (list, tuple)):
        itens = [_do_json(modelo[min(i, len(modelo) - 1)], x) for i, x in enumerate(v)]
        return type(modelo)(itens)
    if isinstance(modelo, dict):
        exemplo = next(iter(modelo.values()))
        return {k: _do_json(exemplo, x) for k, x in v.items()}
    return str(v)


_PADROES = {n: getattr(tabelas, n) for n in _nomes()}


def caminho_tabelas() -> Path:
    return pasta_dados() / ARQUIVO_TABELAS


def salvar_tabelas() -> None:
    dados = {"_LEIA-ME": "Valores usados nos cálculos. Altere com cuidado e reinicie o programa. "
                         "Alíquotas em fração (0.075 = 7,5%). null = sem limite."}
    dados.update({n: _para_json(getattr(tabelas, n)) for n in _nomes()})
    caminho_tabelas().write_text(json.dumps(dados, indent=2, ensure_ascii=False), encoding="utf-8")


def carregar_tabelas() -> None:
    """Aplica tabelas.json sobre os valores padrão; cria o arquivo se não existir.
    Chaves novas (de versões futuras do programa) são acrescentadas ao arquivo."""
    caminho = caminho_tabelas()
    if not caminho.exists():
        salvar_tabelas()
        return
    dados = json.loads(caminho.read_text(encoding="utf-8"))
    for nome, padrao in _PADROES.items():
        if nome in dados:
            try:
                setattr(tabelas, nome, _do_json(padrao, dados[nome]))
            except Exception as e:
                raise ValueError(f"valor inválido para {nome} em {caminho}: {e}") from e
    if set(_PADROES) - set(dados):
        salvar_tabelas()
