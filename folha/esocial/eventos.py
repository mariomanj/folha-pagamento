"""Montagem dos XMLs dos eventos (leiaute S-1.3). A ordem dos elementos segue
os esquemas oficiais em recursos/. Os XMLs saem sem assinatura."""
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal as D

from lxml import etree

from ..calculo import Funcionario, Holerite
from .rubricas import Rubrica, rubrica_do_item

VERSAO_LEIAUTE = "v_S_01_03_00"
NS = {
    "S-1010": f"http://www.esocial.gov.br/schema/evt/evtTabRubrica/{VERSAO_LEIAUTE}",
    "S-1200": f"http://www.esocial.gov.br/schema/evt/evtRemun/{VERSAO_LEIAUTE}",
    "S-1210": f"http://www.esocial.gov.br/schema/evt/evtPgtos/{VERSAO_LEIAUTE}",
    "S-1299": f"http://www.esocial.gov.br/schema/evt/evtFechaEvPer/{VERSAO_LEIAUTE}",
}
RAIZ_EVENTO = {"S-1010": "evtTabRubrica", "S-1200": "evtRemun", "S-1210": "evtPgtos", "S-1299": "evtFechaEvPer"}
VERSAO_PROGRAMA = "FolhaPagamento 1.1"
CR_TRABALHO_ASSALARIADO = "056107"  # código de receita do IRRF sobre salários


def somente_digitos(texto: str) -> str:
    return "".join(c for c in texto if c.isdigit())


def cpf_valido(cpf: str) -> bool:
    cpf = somente_digitos(cpf)
    if len(cpf) != 11 or cpf == cpf[0] * 11:
        return False
    for n in (9, 10):
        soma = sum(int(cpf[i]) * (n + 1 - i) for i in range(n))
        if (soma * 10 % 11) % 10 != int(cpf[n]):
            return False
    return True


def cnpj_valido(cnpj: str) -> bool:
    cnpj = somente_digitos(cnpj)
    if len(cnpj) != 14 or cnpj == cnpj[0] * 14:
        return False
    for n in (12, 13):
        pesos = list(range(n - 7, 1, -1)) + list(range(9, 1, -1))
        resto = sum(int(cnpj[i]) * pesos[i] for i in range(n)) % 11
        if (0 if resto < 2 else 11 - resto) != int(cnpj[n]):
            return False
    return True


def valor(v: D) -> str:
    return f"{v:.2f}"


@dataclass
class Empregador:
    cnpj: str              # 14 dígitos
    estabelecimento: str   # CNPJ do estabelecimento (14 dígitos)
    lotacao: str           # codLotacao do S-1020
    tab_rubricas: str      # ideTabRubr
    ambiente: int          # tpAmb

    @property
    def raiz(self) -> str:
        return self.cnpj[:8]


class Gerador:
    """Cria eventos com Id único: ID + tipo inscrição + CNPJ base completado
    com zeros à direita (14) + data/hora + sequencial de 5 dígitos."""

    def __init__(self, empregador: Empregador, agora: datetime | None = None):
        self.emp = empregador
        self.agora = agora or datetime.now()
        self.seq = 0

    def _novo_id(self) -> str:
        self.seq += 1
        return f"ID1{self.emp.raiz.ljust(14, '0')}{self.agora:%Y%m%d%H%M%S}{self.seq:05d}"

    def _inicio(self, tipo: str) -> tuple[etree._Element, etree._Element, str]:
        ns = NS[tipo]
        raiz = etree.Element(f"{{{ns}}}eSocial", nsmap={None: ns})
        id_evento = self._novo_id()
        evt = etree.SubElement(raiz, f"{{{ns}}}{RAIZ_EVENTO[tipo]}", Id=id_evento)
        return raiz, evt, id_evento

    @staticmethod
    def _sub(pai, tag, texto=None):
        ns = etree.QName(pai).namespace
        el = etree.SubElement(pai, f"{{{ns}}}{tag}")
        if texto is not None:
            el.text = str(texto)
        return el

    def _ide_evento(self, evt, indRetif=None, nrRecibo=None, indApuracao=None, perApur=None):
        s = self._sub
        ide = s(evt, "ideEvento")
        if indRetif is not None:
            s(ide, "indRetif", indRetif)
            if nrRecibo:
                s(ide, "nrRecibo", nrRecibo)
        if indApuracao is not None:
            s(ide, "indApuracao", indApuracao)
        if perApur is not None:
            s(ide, "perApur", perApur)
        s(ide, "tpAmb", self.emp.ambiente)
        s(ide, "procEmi", 1)
        s(ide, "verProc", VERSAO_PROGRAMA)
        emp = s(evt, "ideEmpregador")
        s(emp, "tpInsc", 1)
        s(emp, "nrInsc", self.emp.raiz)

    @staticmethod
    def _bytes(raiz) -> bytes:
        return etree.tostring(raiz, encoding="utf-8")

    # --- S-1010 ---------------------------------------------------------------

    def s1010(self, r: Rubrica, ini_valid: str, alteracao: bool = False) -> tuple[str, bytes]:
        s = self._sub
        raiz, evt, id_evento = self._inicio("S-1010")
        self._ide_evento(evt)
        operacao = s(s(evt, "infoRubrica"), "alteracao" if alteracao else "inclusao")
        ide = s(operacao, "ideRubrica")
        s(ide, "codRubr", r.codigo)
        s(ide, "ideTabRubr", self.emp.tab_rubricas)
        s(ide, "iniValid", ini_valid)
        dados = s(operacao, "dadosRubrica")
        s(dados, "dscRubr", r.descricao)
        s(dados, "natRubr", r.natureza)
        s(dados, "tpRubr", r.tipo)
        s(dados, "codIncCP", r.inc_cp)
        s(dados, "codIncIRRF", r.inc_irrf)
        s(dados, "codIncFGTS", r.inc_fgts)
        return id_evento, self._bytes(raiz)

    # --- S-1200 ---------------------------------------------------------------

    def s1200(self, f: Funcionario, competencia: str, demonstrativos: list[tuple[str, str, Holerite]],
              rubricas: list[Rubrica], recibo_retificado: str | None = None) -> tuple[str, bytes]:
        """demonstrativos: (ideDmDev, tipo de folha, recibo)."""
        s = self._sub
        raiz, evt, id_evento = self._inicio("S-1200")
        self._ide_evento(evt, indRetif=2 if recibo_retificado else 1, nrRecibo=recibo_retificado,
                         indApuracao=1, perApur=competencia)
        s(s(evt, "ideTrabalhador"), "cpfTrab", somente_digitos(f.cpf))
        for ide_dm_dev, folha, h in demonstrativos:
            dm = s(evt, "dmDev")
            s(dm, "ideDmDev", ide_dm_dev)
            s(dm, "codCateg", f.categoria)
            estab = s(s(dm, "infoPerApur"), "ideEstabLot")
            s(estab, "tpInsc", 1)
            s(estab, "nrInsc", self.emp.estabelecimento)
            s(estab, "codLotacao", self.emp.lotacao)
            remun = s(estab, "remunPerApur")
            s(remun, "matricula", f.matricula_esocial)
            for descricao, v in [*h.proventos.items(), *h.descontos.items()]:
                if v <= 0:
                    continue
                r = rubrica_do_item(rubricas, folha, descricao)
                item = s(remun, "itensRemun")
                s(item, "codRubr", r.codigo)
                s(item, "ideTabRubr", self.emp.tab_rubricas)
                s(item, "vrRubr", valor(v))
                s(item, "indApurIR", 0)
            if 100 <= f.categoria < 400:  # obrigatório para empregados (codCateg 1XX, 2XX, 3XX)
                s(s(remun, "infoAgNocivo"), "grauExp", f.grau_exposicao)
        return id_evento, self._bytes(raiz)

    # --- S-1210 ---------------------------------------------------------------

    def s1210(self, cpf: str, competencia: str, pagamentos: list[tuple[date, str, str, D]],
              pensao: tuple[str, D] | None = None, recibo_retificado: str | None = None) -> tuple[str, bytes]:
        """pagamentos: (data, perRef, ideDmDev, líquido). pensao: (CPF do
        beneficiário, valor descontado) — exigida quando há rubrica de pensão."""
        s = self._sub
        raiz, evt, id_evento = self._inicio("S-1210")
        self._ide_evento(evt, indRetif=2 if recibo_retificado else 1, nrRecibo=recibo_retificado,
                         perApur=competencia)
        benef = s(evt, "ideBenef")
        s(benef, "cpfBenef", somente_digitos(cpf))
        for data_pgto, per_ref, ide_dm_dev, liquido in pagamentos:
            pg = s(benef, "infoPgto")
            s(pg, "dtPgto", data_pgto.isoformat())
            s(pg, "tpPgto", 1)
            s(pg, "perRef", per_ref)
            s(pg, "ideDmDev", ide_dm_dev)
            s(pg, "vrLiq", valor(max(liquido, D(0))))
        if pensao:
            cr = s(s(benef, "infoIRComplem"), "infoIRCR")
            s(cr, "tpCR", CR_TRABALHO_ASSALARIADO)
            pa = s(cr, "penAlim")
            s(pa, "tpRend", 11)
            s(pa, "cpfDep", somente_digitos(pensao[0]))
            s(pa, "vlrDedPenAlim", valor(pensao[1]))
        return id_evento, self._bytes(raiz)

    # --- S-1299 ---------------------------------------------------------------

    def s1299(self, competencia: str, tem_remuneracao: bool, tem_pagamentos: bool) -> tuple[str, bytes]:
        s = self._sub
        raiz, evt, id_evento = self._inicio("S-1299")
        self._ide_evento(evt, indApuracao=1, perApur=competencia)
        fech = s(evt, "infoFech")
        s(fech, "evtRemun", "S" if tem_remuneracao else "N")
        s(fech, "evtPgtos", "S" if tem_pagamentos else "N")
        s(fech, "evtComProd", "N")
        s(fech, "evtContratAvNP", "N")
        s(fech, "evtInfoComplPer", "N")
        return id_evento, self._bytes(raiz)
