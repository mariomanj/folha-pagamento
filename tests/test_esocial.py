import base64
import hashlib
import os
import re
import tempfile
import unittest
import xml.etree.ElementTree as ET
from datetime import date
from decimal import Decimal as D
from pathlib import Path
from unittest import mock

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from lxml import etree

from folha import banco, config, servicos, tabelas
from folha.calculo import Funcionario, Lancamento, calcular_folha
from folha.esocial import assinatura, eventos as ev, rubricas as rb, servico, validacao, webservice as ws
from folha.ferias import calcular_ferias

DS = "{http://www.w3.org/2000/09/xmldsig#}"
EMPREGADOR = ev.Empregador("11222333000181", "11222333000181", "LOT01", "FOLHA", 2)


def verificar_assinatura(xml: bytes):
    """Conferência independente da biblioteca usada para assinar: C14N da
    biblioteca padrão do Python + cryptography."""
    ET.register_namespace("", "http://www.w3.org/2000/09/xmldsig#")
    sem_assinatura = re.sub(r'<Signature xmlns="http://www.w3.org/2000/09/xmldsig#">.*</Signature>', "",
                            xml.decode(), flags=re.S)
    digest = base64.b64encode(hashlib.sha256(ET.canonicalize(sem_assinatura).encode()).digest()).decode()
    sig = ET.fromstring(xml).find(DS + "Signature")
    info = sig.find(DS + "SignedInfo")
    if info.find(f"{DS}Reference/{DS}DigestValue").text != digest:
        raise ValueError("digest diferente")
    cert = x509.load_der_x509_certificate(
        base64.b64decode(sig.find(f"{DS}KeyInfo/{DS}X509Data/{DS}X509Certificate").text))
    cert.public_key().verify(base64.b64decode(sig.find(DS + "SignatureValue").text),
                             ET.canonicalize(ET.tostring(info, encoding="unicode")).encode(),
                             padding.PKCS1v15(), hashes.SHA256())


def funcionario_completo(**extra):
    dados = dict(nome="Ana", salario=D("3500"), cpf="529.982.247-25", matricula_esocial="000123",
                 periculosidade=True, pensao=D("300"), cpf_pensao="111.444.777-35", usa_vt=True, valor_vt=D("200"),
                 desconto_vr=D("50"), adiantamento_pct=D("40"), filhos_sf=1)
    dados.update(extra)
    return Funcionario(**dados)


class TestDocumentos(unittest.TestCase):
    def test_cpf_e_cnpj(self):
        self.assertTrue(ev.cpf_valido("529.982.247-25"))
        self.assertFalse(ev.cpf_valido("529.982.247-24"))
        self.assertFalse(ev.cpf_valido("111.111.111-11"))
        self.assertTrue(ev.cnpj_valido("11.222.333/0001-81"))
        self.assertFalse(ev.cnpj_valido("11.222.333/0001-82"))


class TestEventos(unittest.TestCase):
    def setUp(self):
        self.g = ev.Gerador(EMPREGADOR)
        self.cert = assinatura.certificado_teste()

    def _confere(self, tipo, xml):
        assinado = assinatura.assinar(xml, self.cert)
        self.assertEqual(validacao.erros(tipo, assinado), [])
        verificar_assinatura(assinado)
        return assinado

    def test_id_do_evento(self):
        id_evento, _ = self.g.s1299("2026-10", True, False)
        self.assertRegex(id_evento, r"^ID111222333000000\d{14}00001$")
        self.assertEqual(len(id_evento), 36)

    def test_todos_os_eventos_validam_no_esquema_oficial(self):
        f = funcionario_completo()
        mensal = calcular_folha(f, Lancamento(horas_extras_50=D("8"), horas_extras_100=D("2"),
                                              horas_noturnas=D("10"), comissoes=D("100"), faltas_dias=D("1"),
                                              dias_ferias=D("10"), outros_proventos=D("10"),
                                              outros_descontos=D("5"), plano_saude=D("150"),
                                              emprestimo_consignado=D("80")), "2026-10")
        ferias = calcular_ferias(f, dias=20, abono=10)
        for r in rb.PADRAO:
            self._confere("S-1010", self.g.s1010(r, "2026-11")[1])
        self._confere("S-1010", self.g.s1010(rb.PADRAO[0], "2026-11", alteracao=True)[1])
        self._confere("S-1200", self.g.s1200(f, "2026-10", [("FP202610M", "mensal", mensal),
                                                            ("FP202610F", "ferias", ferias)], rb.PADRAO)[1])
        self._confere("S-1200", self.g.s1200(f, "2026-10", [("FP202610M", "mensal", mensal)], rb.PADRAO,
                                             recibo_retificado="1.1.0000000000000000001")[1])
        self._confere("S-1210", self.g.s1210(f.cpf, "2026-11", [(date(2026, 11, 5), "2026-10", "FP202610M",
                                                                 mensal.liquido)], (f.cpf_pensao, D("300")))[1])
        self._confere("S-1299", self.g.s1299("2026-10", True, True)[1])

    def test_todo_item_de_recibo_tem_rubrica(self):
        f = funcionario_completo(insalubridade=20, periculosidade=False)
        mensal = calcular_folha(f, Lancamento(horas_extras_50=D("1"), horas_extras_100=D("1"),
                                              horas_noturnas=D("1"), comissoes=D("1"), faltas_dias=D("1"),
                                              dias_ferias=D("5"), outros_proventos=D("1"),
                                              outros_descontos=D("1"), desconto_vt=D("1"), plano_saude=D("1"),
                                              plano_odonto=D("1"), vale_alimentacao=D("1"), seguro_vida=D("1"),
                                              emprestimo_consignado=D("1"), contribuicao_sindical=D("1"),
                                              convenio_farmacia=D("1")), "2026-10")
        for folha, h in [("mensal", mensal), ("mensal", calcular_folha(funcionario_completo())),
                         ("ferias", calcular_ferias(f, 20, 10))]:
            for descricao in [*h.proventos, *h.descontos]:
                rb.rubrica_do_item(rb.PADRAO, folha, descricao)

    def test_assinatura_adulterada_e_detectada(self):
        assinado = self._confere("S-1299", self.g.s1299("2026-10", True, True)[1])
        with self.assertRaises(ValueError):
            verificar_assinatura(assinado.replace(b"<evtRemun>S</evtRemun>", b"<evtRemun>N</evtRemun>"))

    def test_lote_valida_e_tem_eventos_assinados(self):
        assinados = [(i, assinatura.assinar(x, self.cert)) for i, x in
                     [self.g.s1299("2026-10", True, False), self.g.s1299("2026-09", True, False)]]
        lote = ws.montar_lote(3, EMPREGADOR.cnpj, EMPREGADOR.cnpj, assinados)
        self.assertEqual(len(etree.fromstring(lote).xpath("//*[local-name()='evento']")), 2)
        env = etree.fromstring(ws.envelope_envio(lote))
        self.assertEqual(env.xpath("local-name(/*/*[2]/*)"), "EnviarLoteEventos")


# --- servidor simulado -----------------------------------------------------------

RET_ENVIO = """<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"><s:Body>
<EnviarLoteEventosResponse xmlns="http://www.esocial.gov.br/servicos/empregador/lote/eventos/envio/v1_1_0">
<EnviarLoteEventosResult><eSocial xmlns="http://www.esocial.gov.br/schema/lote/eventos/envio/retornoEnvio/v1_1_0">
<retornoEnvioLoteEventos><status><cdResposta>{cd}</cdResposta><descResposta>{desc}</descResposta>{ocorr}</status>
{recepcao}</retornoEnvioLoteEventos></eSocial></EnviarLoteEventosResult></EnviarLoteEventosResponse></s:Body></s:Envelope>"""
RECEPCAO = ("<dadosRecepcaoLote><dhRecepcao>2026-10-21T10:00:00</dhRecepcao><versaoAplicativoRecepcao>1"
            "</versaoAplicativoRecepcao><protocoloEnvio>{prot}</protocoloEnvio></dadosRecepcaoLote>")
RET_EVENTO = """<evento Id="{id}"><retornoEvento><eSocial xmlns="http://www.esocial.gov.br/schema/evt/retornoEvento/v1_3_0">
<retornoEvento Id="{id}"><processamento><cdResposta>{cd}</cdResposta><descResposta>{desc}</descResposta>
<versaoAppProcessamento>1</versaoAppProcessamento><dhProcessamento>2026-10-21T10:01:00</dhProcessamento>{ocorr}
</processamento>{recibo}</retornoEvento></eSocial></retornoEvento></evento>"""
RET_PROC = """<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"><s:Body>
<ConsultarLoteEventosResponse xmlns="http://www.esocial.gov.br/servicos/empregador/lote/eventos/envio/consulta/retornoProcessamento/v1_1_0">
<ConsultarLoteEventosResult><eSocial xmlns="http://www.esocial.gov.br/schema/lote/eventos/envio/retornoProcessamento/v1_3_0">
<retornoProcessamentoLoteEventos><status><cdResposta>{cd}</cdResposta><descResposta>ok</descResposta></status>
<retornoEventos>{eventos}</retornoEventos></retornoProcessamentoLoteEventos></eSocial>
</ConsultarLoteEventosResult></ConsultarLoteEventosResponse></s:Body></s:Envelope>"""
OCORRENCIA = ("<ocorrencias><ocorrencia><tipo>1</tipo><codigo>{cod}</codigo><descricao>{desc}</descricao>"
              "<localizacao>/eSocial/evtRemun</localizacao></ocorrencia></ocorrencias>")


class ServidorFalso:
    """Imita o eSocial: guarda os lotes recebidos e responde à consulta.
    `rejeitar` = conjunto de tipos de evento a recusar."""

    def __init__(self):
        self.lotes = {}
        self.rejeitar = set()
        self.recibos = 0
        self.envelopes = []

    def __call__(self, url, acao, envelope, certificado, tempo_limite=120):
        self.envelopes.append(envelope)
        doc = etree.fromstring(envelope)
        if acao == ws.ACAO_ENVIO:
            for evt in doc.xpath("//*[local-name()='evento']"):
                verificar_assinatura(etree.tostring(evt[0]))  # cada evento chega assinado e íntegro
            prot = f"1.2.202610.{len(self.lotes) + 1:07d}"
            self.lotes[prot] = [(e.get("Id"), etree.QName(e[0][0]).localname)
                                for e in doc.xpath("//*[local-name()='evento']")]
            return RET_ENVIO.format(cd=201, desc="Lote Recebido com Sucesso.", ocorr="",
                                    recepcao=RECEPCAO.format(prot=prot)).encode()
        prot = doc.xpath("string(//*[local-name()='protocoloEnvio'])")
        eventos = []
        for id_evento, raiz in self.lotes[prot]:
            if raiz in self.rejeitar:
                eventos.append(RET_EVENTO.format(id=id_evento, cd=401, desc="Erro", recibo="",
                                                 ocorr=OCORRENCIA.format(cod=1234, desc="Trabalhador não cadastrado")))
            else:
                self.recibos += 1
                eventos.append(RET_EVENTO.format(id=id_evento, cd=201, desc="Sucesso", ocorr="",
                                                 recibo=f"<recibo><nrRecibo>1.1.{self.recibos:019d}</nrRecibo></recibo>"))
        return RET_PROC.format(cd=201, eventos="".join(eventos)).encode()


class TestCicloMensal(unittest.TestCase):
    def setUp(self):
        self.pasta = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"FOLHA_DADOS": self.pasta.name})
        self.env.start()
        self.valores = {n: getattr(tabelas, n) for n in ("EMPRESA_CNPJ", "ESOCIAL_COD_LOTACAO",
                                                          "ESOCIAL_INICIO_RUBRICAS", "ESOCIAL_AMBIENTE")}
        tabelas.EMPRESA_CNPJ = "11.222.333/0001-81"
        tabelas.ESOCIAL_COD_LOTACAO = "LOT01"
        tabelas.ESOCIAL_INICIO_RUBRICAS = "2026-10"
        tabelas.ESOCIAL_AMBIENTE = 2
        self.con = banco.conectar(Path(self.pasta.name) / "t.db")
        for f in [funcionario_completo(), Funcionario(nome="Beto", salario=D("2500"), cpf="11144477735",
                                                      matricula_esocial="000124")]:
            banco.inserir_funcionario(self.con, f)
        servicos.processar_mensal(self.con, "2026-09")
        servicos.processar_mensal(self.con, "2026-10")
        servico.definir_data_pagamento(self.con, "2026-09", "mensal", date(2026, 10, 5))
        self.servidor = ServidorFalso()
        self.postar = mock.patch.object(ws, "_postar", self.servidor)
        self.postar.start()
        self.cert = assinatura.Certificado(assinatura.certificado_teste().chave, assinatura.certificado_teste().cert)

    def tearDown(self):
        self.postar.stop()
        self.con.close()
        for n, v in self.valores.items():
            setattr(tabelas, n, v)
        self.env.stop()
        self.pasta.cleanup()

    def _status(self, tipo):
        return sorted(r["status"] for r in servico.listar(self.con, "2026-10", 2) if r["tipo"] == tipo)

    def _ciclo(self):
        etapas = []
        while servico.proxima_etapa(self.con, "2026-10", 2):
            etapas.append(servico.enviar(self.con, "2026-10", self.cert).etapa)
            servico.consultar(self.con, self.cert)
        return etapas

    def test_ciclo_completo_e_retificacao(self):
        r = servico.gerar(self.con, "2026-10")
        self.assertEqual(r.gerados, {"S-1010": len(rb.PADRAO), "S-1200": 2, "S-1210": 2, "S-1299": 1})
        self.assertEqual(self._ciclo(), ["S-1010", "S-1200", "S-1210", "S-1299"])
        self.assertEqual(self._status("S-1200"), ["aceito", "aceito"])
        self.assertEqual(self._status("S-1299"), ["aceito"])

        # nada mudou: nada a gerar
        self.assertEqual(sum(servico.gerar(self.con, "2026-10").gerados.values()), 0)

        # muda a folha de um funcionário: retificação do S-1200 dele + novo fechamento
        banco.salvar_lancamento(self.con, 1, "2026-10", Lancamento(horas_extras_50=D("5")))
        servicos.processar_mensal(self.con, "2026-10")
        r = servico.gerar(self.con, "2026-10")
        self.assertEqual(r.gerados, {"S-1010": 0, "S-1200": 1, "S-1210": 0, "S-1299": 1})
        pendente = [x for x in servico.listar(self.con, "2026-10", 2) if x["tipo"] == "S-1200" and x["status"] == "gerado"][0]
        xml = etree.fromstring(pendente["xml"].encode())
        self.assertEqual(xml.xpath("string(//*[local-name()='indRetif'])"), "2")
        self.assertRegex(xml.xpath("string(//*[local-name()='nrRecibo'])"), r"^1\.1\.\d{19}$")

    def test_rejeicao_bloqueia_etapas_seguintes(self):
        self.servidor.rejeitar = {"evtRemun"}
        servico.gerar(self.con, "2026-10")
        servico.enviar(self.con, "2026-10", self.cert)
        servico.consultar(self.con, self.cert)
        servico.enviar(self.con, "2026-10", self.cert)  # S-1200
        servico.consultar(self.con, self.cert)
        rejeitado = [x for x in servico.listar(self.con, "2026-10", 2) if x["tipo"] == "S-1200"][0]
        self.assertEqual(rejeitado["status"], "rejeitado")
        self.assertIn("Trabalhador não cadastrado", rejeitado["mensagens"])
        with self.assertRaisesRegex(ValueError, "rejeitados"):
            servico.enviar(self.con, "2026-10", self.cert)

    def test_cadastro_incompleto_vira_aviso(self):
        f = banco.obter_funcionario(self.con, 2)
        f.matricula_esocial = ""
        banco.atualizar_funcionario(self.con, f)
        r = servico.gerar(self.con, "2026-10")
        self.assertEqual(r.gerados["S-1200"], 1)
        self.assertTrue(any("matrícula" in a for a in r.avisos))

    def test_configuracao_incompleta(self):
        tabelas.ESOCIAL_COD_LOTACAO = ""
        with self.assertRaisesRegex(ValueError, "lotação"):
            servico.gerar(self.con, "2026-10")

    def test_pagamentos_do_sistema_anterior(self):
        csv = Path(self.pasta.name) / "pg.csv"
        csv.write_text("cpf;data;competencia;ide_dm_dev;valor\n111.444.777-35;05/10/2026;09/2026;ANTIGO0926;2.100,50\n",
                       encoding="utf-8")
        self.assertEqual(servico.importar_pagamentos_externos(self.con, csv), 1)
        servico.gerar(self.con, "2026-10")
        s1210 = [x for x in servico.listar(self.con, "2026-10", 2) if x["chave"] == "S-1210|2026-10|11144477735"][0]
        xml = s1210["xml"]
        self.assertIn("<ideDmDev>ANTIGO0926</ideDmDev>", xml)
        self.assertIn("<vrLiq>2100.50</vrLiq>", xml)


if __name__ == "__main__":
    unittest.main()
