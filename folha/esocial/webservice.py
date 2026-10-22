"""Comunicação com os webservices do eSocial (SOAP 1.1 com certificado de
cliente). Endereços e ações conforme o Manual do Desenvolvedor v1.16 e os
WSDLs do Pacote de Comunicação v1.6."""
import os
import secrets
import ssl
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from lxml import etree

from . import validacao
from .assinatura import Certificado, pem_cliente

URLS = {
    1: ("https://webservices.envio.esocial.gov.br/servicos/empregador/enviarloteeventos/WsEnviarLoteEventos.svc",
        "https://webservices.consulta.esocial.gov.br/servicos/empregador/consultarloteeventos/"
        "WsConsultarLoteEventos.svc"),
    2: ("https://webservices.producaorestrita.esocial.gov.br/servicos/empregador/enviarloteeventos/"
        "WsEnviarLoteEventos.svc",
        "https://webservices.producaorestrita.esocial.gov.br/servicos/empregador/consultarloteeventos/"
        "WsConsultarLoteEventos.svc"),
}
SOAP = "http://schemas.xmlsoap.org/soap/envelope/"
NS_LOTE = "http://www.esocial.gov.br/schema/lote/eventos/envio/v1_1_1"
NS_CONSULTA = "http://www.esocial.gov.br/schema/lote/eventos/envio/consulta/retornoProcessamento/v1_0_0"
SERVICO_ENVIO = "http://www.esocial.gov.br/servicos/empregador/lote/eventos/envio/v1_1_0"
SERVICO_CONSULTA = ("http://www.esocial.gov.br/servicos/empregador/lote/eventos/envio/consulta/"
                    "retornoProcessamento/v1_1_0")
ACAO_ENVIO = f"{SERVICO_ENVIO}/ServicoEnviarLoteEventos/EnviarLoteEventos"
ACAO_CONSULTA = f"{SERVICO_CONSULTA}/ServicoConsultarLoteEventos/ConsultarLoteEventos"
MAX_EVENTOS_LOTE = 50
GRUPO = {"S-1010": 1, "S-1200": 3, "S-1210": 3, "S-1299": 3}  # 1 tabelas, 2 não periódicos, 3 periódicos


class ErroComunicacao(Exception):
    pass


@dataclass
class Ocorrencia:
    codigo: str
    descricao: str
    tipo: str = ""          # 1 erro, 2 advertência
    localizacao: str = ""

    def __str__(self):
        local = f" [{self.localizacao}]" if self.localizacao else ""
        return f"{self.codigo} - {self.descricao}{local}"


@dataclass
class RetornoEnvio:
    codigo: int
    descricao: str
    protocolo: str = ""
    ocorrencias: list[Ocorrencia] = field(default_factory=list)

    @property
    def aceito(self) -> bool:
        return self.codigo == 201 and bool(self.protocolo)


@dataclass
class RetornoEvento:
    id_evento: str
    codigo: int
    descricao: str
    recibo: str = ""
    ocorrencias: list[Ocorrencia] = field(default_factory=list)

    @property
    def aceito(self) -> bool:
        return bool(self.recibo)


@dataclass
class RetornoProcessamento:
    codigo: int           # 101 aguardando, 201 processado, 202 com advertências, 4xx/5xx erro
    descricao: str
    eventos: list[RetornoEvento] = field(default_factory=list)
    ocorrencias: list[Ocorrencia] = field(default_factory=list)
    tempo_estimado: int | None = None

    @property
    def em_processamento(self) -> bool:
        return self.codigo == 101


# --- montagem -------------------------------------------------------------------

def montar_lote(grupo: int, cnpj_empregador: str, transmissor: str, eventos: list[tuple[str, bytes]]) -> bytes:
    """eventos: (Id, XML assinado). O transmissor é o titular do certificado
    (CNPJ com 14 dígitos ou CPF com 11)."""
    if not 1 <= len(eventos) <= MAX_EVENTOS_LOTE:
        raise ValueError(f"um lote deve ter de 1 a {MAX_EVENTOS_LOTE} eventos")
    raiz = etree.Element(f"{{{NS_LOTE}}}eSocial", nsmap={None: NS_LOTE})
    lote = etree.SubElement(raiz, f"{{{NS_LOTE}}}envioLoteEventos", grupo=str(grupo))

    def sub(pai, tag, texto=None):
        el = etree.SubElement(pai, f"{{{NS_LOTE}}}{tag}")
        el.text = texto
        return el

    emp = sub(lote, "ideEmpregador")
    sub(emp, "tpInsc", "1")
    sub(emp, "nrInsc", cnpj_empregador[:8])
    trans = sub(lote, "ideTransmissor")
    sub(trans, "tpInsc", "1" if len(transmissor) == 14 else "2")
    sub(trans, "nrInsc", transmissor)
    lista = sub(lote, "eventos")
    for id_evento, xml in eventos:
        evento = sub(lista, "evento")
        evento.set("Id", id_evento)
        evento.append(etree.fromstring(xml))
    xml_lote = etree.tostring(raiz, encoding="utf-8")
    if erros := validacao.erros("lote", xml_lote):
        raise ValueError("lote inválido: " + "; ".join(erros[:3]))
    return xml_lote


def _envelope(servico: str, operacao: str, parametro: str, conteudo: bytes) -> bytes:
    env = etree.Element(f"{{{SOAP}}}Envelope", nsmap={"soapenv": SOAP, "v1": servico})
    etree.SubElement(env, f"{{{SOAP}}}Header")
    corpo = etree.SubElement(env, f"{{{SOAP}}}Body")
    op = etree.SubElement(corpo, f"{{{servico}}}{operacao}")
    etree.SubElement(op, f"{{{servico}}}{parametro}").append(etree.fromstring(conteudo))
    return etree.tostring(env, encoding="utf-8", xml_declaration=True)


def envelope_envio(xml_lote: bytes) -> bytes:
    return _envelope(SERVICO_ENVIO, "EnviarLoteEventos", "loteEventos", xml_lote)


def envelope_consulta(protocolo: str) -> bytes:
    raiz = etree.Element(f"{{{NS_CONSULTA}}}eSocial", nsmap={None: NS_CONSULTA})
    etree.SubElement(etree.SubElement(raiz, f"{{{NS_CONSULTA}}}consultaLoteEventos"),
                     f"{{{NS_CONSULTA}}}protocoloEnvio").text = protocolo
    return _envelope(SERVICO_CONSULTA, "ConsultarLoteEventos", "consulta", etree.tostring(raiz))


# --- leitura das respostas --------------------------------------------------------

def _filho(no, nome):
    if no is None:
        return None
    achados = no.xpath(f"./*[local-name()='{nome}']")
    return achados[0] if achados else None


def _texto(no, *caminho) -> str:
    for nome in caminho:
        no = _filho(no, nome)
    return (no.text or "").strip() if no is not None else ""


def _ocorrencias(no) -> list[Ocorrencia]:
    lista = _filho(no, "ocorrencias")
    if lista is None:
        return []
    return [Ocorrencia(_texto(o, "codigo"), _texto(o, "descricao"), _texto(o, "tipo"), _texto(o, "localizacao"))
            for o in lista.xpath("./*[local-name()='ocorrencia']")]


def _primeiro(xml: bytes, nome: str):
    try:
        doc = etree.fromstring(xml)
    except etree.XMLSyntaxError as e:
        raise ErroComunicacao(f"resposta do eSocial ilegível: {e}") from e
    if falha := doc.xpath("//*[local-name()='Fault']"):
        raise ErroComunicacao("o eSocial recusou a requisição: " + _texto(falha[0], "faultstring"))
    achados = doc.xpath(f"//*[local-name()='{nome}']")
    if not achados:
        raise ErroComunicacao(f"resposta do eSocial sem o elemento {nome}")
    return achados[0]


def ler_retorno_envio(xml: bytes) -> RetornoEnvio:
    r = _primeiro(xml, "retornoEnvioLoteEventos")
    status = _filho(r, "status")
    return RetornoEnvio(int(_texto(status, "cdResposta") or 0), _texto(status, "descResposta"),
                        _texto(r, "dadosRecepcaoLote", "protocoloEnvio"), _ocorrencias(status))


def ler_retorno_processamento(xml: bytes) -> RetornoProcessamento:
    r = _primeiro(xml, "retornoProcessamentoLoteEventos")
    status = _filho(r, "status")
    tempo = _texto(status, "tempoEstimadoConclusao")
    ret = RetornoProcessamento(int(_texto(status, "cdResposta") or 0), _texto(status, "descResposta"),
                               ocorrencias=_ocorrencias(status), tempo_estimado=int(tempo) if tempo else None)
    for evento in r.xpath("./*[local-name()='retornoEventos']/*[local-name()='evento']"):
        # evento/retornoEvento/eSocial/retornoEvento: o de dentro tem o processamento
        retorno = evento.xpath(".//*[local-name()='retornoEvento'][*[local-name()='processamento']]")
        proc = _filho(retorno[0], "processamento") if retorno else None
        ret.eventos.append(RetornoEvento(
            evento.get("Id", ""), int(_texto(proc, "cdResposta") or 0), _texto(proc, "descResposta"),
            _texto(retorno[0], "recibo", "nrRecibo") if retorno else "", _ocorrencias(proc)))
    return ret


# --- transporte ------------------------------------------------------------------

def _contexto_tls(certificado: Certificado) -> ssl.SSLContext:
    """Confia no repositório do Windows e nas raízes ICP-Brasil embutidas, e
    apresenta o certificado A1 ao servidor. A chave vai para um arquivo
    temporário cifrado com senha aleatória (o módulo ssl só lê de arquivos),
    apagado logo após a carga."""
    ctx = ssl.create_default_context()
    ctx.load_verify_locations(cadata=(validacao.RECURSOS / "icp_brasil_raizes.pem").read_text(encoding="ascii"))
    senha = secrets.token_bytes(32).hex().encode()
    cert_pem, chave_pem = pem_cliente(certificado, senha)
    pasta = tempfile.mkdtemp(prefix="folha_tls_")
    arq_cert, arq_chave = os.path.join(pasta, "c.pem"), os.path.join(pasta, "k.pem")
    try:
        with open(arq_cert, "wb") as a:
            a.write(cert_pem)
        with open(arq_chave, "wb") as a:
            a.write(chave_pem)
        ctx.load_cert_chain(arq_cert, arq_chave, password=senha)
    finally:
        for arq in (arq_cert, arq_chave):
            try:
                os.remove(arq)
            except OSError:
                pass
        os.rmdir(pasta)
    return ctx


def _postar(url: str, acao: str, envelope: bytes, certificado: Certificado, tempo_limite=120) -> bytes:
    if certificado.teste:
        raise ValueError("o certificado de teste não pode ser usado para transmitir")
    req = urllib.request.Request(url, data=envelope, method="POST", headers={
        "Content-Type": "text/xml; charset=utf-8", "SOAPAction": f'"{acao}"'})
    abridor = urllib.request.build_opener(urllib.request.HTTPSHandler(context=_contexto_tls(certificado)))
    try:
        with abridor.open(req, timeout=tempo_limite) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        corpo = e.read()
        if b"Fault" in corpo:
            return corpo  # falha SOAP: tratada na leitura da resposta
        raise ErroComunicacao(f"o servidor do eSocial respondeu HTTP {e.code} {e.reason}") from e
    except urllib.error.URLError as e:
        motivo = e.reason
        if isinstance(motivo, ssl.SSLCertVerificationError):
            raise ErroComunicacao(
                "não foi possível confirmar a identidade do servidor do eSocial "
                f"({motivo.verify_message}). Se houver antivírus inspecionando conexões HTTPS "
                "(ex.: Norton Web/Mail Shield, Kaspersky, Avast), crie uma exceção para *.esocial.gov.br.") from e
        if isinstance(motivo, ssl.SSLError):
            raise ErroComunicacao(
                f"falha na conexão segura com o eSocial ({motivo}). Verifique se o certificado A1 é válido "
                "e se algum antivírus está inspecionando conexões HTTPS.") from e
        raise ErroComunicacao(f"sem conexão com o eSocial: {motivo}. Verifique a internet.") from e
    except TimeoutError as e:
        raise ErroComunicacao("o eSocial não respondeu a tempo; tente novamente em alguns minutos") from e


def enviar_lote(xml_lote: bytes, certificado: Certificado, ambiente: int) -> RetornoEnvio:
    return ler_retorno_envio(_postar(URLS[ambiente][0], ACAO_ENVIO, envelope_envio(xml_lote), certificado))


def consultar_lote(protocolo: str, certificado: Certificado, ambiente: int) -> RetornoProcessamento:
    return ler_retorno_processamento(
        _postar(URLS[ambiente][1], ACAO_CONSULTA, envelope_consulta(protocolo), certificado))
