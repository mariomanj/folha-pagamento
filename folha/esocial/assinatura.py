"""Certificado A1 e assinatura XML dos eventos (Manual do Desenvolvedor, item 6.7):
XMLDSig envelopada, C14N 1.0, RSA-SHA256, apenas o certificado do titular."""
import base64
import copy
import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID
from lxml import etree

DS = "http://www.w3.org/2000/09/xmldsig#"
C14N = "http://www.w3.org/TR/2001/REC-xml-c14n-20010315"
RSA_SHA256 = "http://www.w3.org/2001/04/xmldsig-more#rsa-sha256"
SHA256 = "http://www.w3.org/2001/04/xmlenc#sha256"
ENVELOPED = "http://www.w3.org/2000/09/xmldsig#enveloped-signature"
OID_CNPJ = "2.16.76.1.3.3"  # otherName do e-CNPJ (ICP-Brasil)


@dataclass
class Certificado:
    chave: rsa.RSAPrivateKey
    cert: x509.Certificate
    teste: bool = False

    @property
    def titular(self) -> str:
        nomes = self.cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
        return nomes[0].value if nomes else self.cert.subject.rfc4514_string()

    @property
    def validade(self) -> datetime:
        return self.cert.not_valid_after_utc

    @property
    def documento(self) -> str:
        """CNPJ (14 dígitos) ou CPF (11) do titular, pelo padrão ICP-Brasil
        'NOME:DOCUMENTO' no nome comum ou pela extensão do e-CNPJ."""
        if m := re.search(r":(\d{14}|\d{11})$", self.titular):
            return m[1]
        try:
            san = self.cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
            for outro in san:
                if isinstance(outro, x509.OtherName) and outro.type_id.dotted_string == OID_CNPJ:
                    if m := re.search(rb"\d{14}", outro.value):
                        return m[0].decode()
        except x509.ExtensionNotFound:
            pass
        return ""


def carregar_pfx(caminho: str | Path, senha: str) -> Certificado:
    try:
        dados = Path(caminho).read_bytes()
    except OSError as e:
        raise ValueError(f"não foi possível ler o certificado: {e}") from e
    try:
        chave, cert, _ = pkcs12.load_key_and_certificates(dados, senha.encode())
    except ValueError as e:
        raise ValueError("senha do certificado incorreta ou arquivo .pfx inválido") from e
    if chave is None or cert is None:
        raise ValueError("o arquivo .pfx não contém a chave privada do certificado")
    agora = datetime.now(timezone.utc)
    if agora > cert.not_valid_after_utc:
        raise ValueError(f"certificado vencido em {cert.not_valid_after_utc:%d/%m/%Y}")
    if agora < cert.not_valid_before_utc:
        raise ValueError(f"certificado válido somente a partir de {cert.not_valid_before_utc:%d/%m/%Y}")
    return Certificado(chave, cert)


@lru_cache(maxsize=1)
def certificado_teste() -> Certificado:
    """Certificado autoassinado, só para validar a estrutura dos XMLs sem pedir a
    senha do certificado real. Nunca é usado para transmitir."""
    chave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    nome = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "TESTE LOCAL:00000000000000")])
    agora = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(nome).issuer_name(nome).public_key(chave.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(agora - timedelta(days=1))
            .not_valid_after(agora + timedelta(days=365)).sign(chave, hashes.SHA256()))
    return Certificado(chave, cert, teste=True)


def _c14n(no) -> bytes:
    """C14N 1.0 do nó como documento isolado. A libxml2 erra ao canonicalizar uma
    subárvore no contexto do documento quando o namespace padrão é redefinido
    (gera xmlns="" nos netos do SignedInfo). Isolar o nó dá o resultado correto
    aqui porque os eventos só usam namespaces padrão: o único em escopo no
    SignedInfo é o do xmldsig, declarado nele mesmo."""
    return etree.tostring(copy.deepcopy(no), method="c14n", exclusive=False, with_comments=False)


def assinar(xml: bytes, certificado: Certificado) -> bytes:
    """Acrescenta <Signature> como último filho da raiz <eSocial>."""
    raiz = etree.fromstring(xml)
    for antiga in raiz.findall(f"{{{DS}}}Signature"):
        raiz.remove(antiga)
    # Transformação enveloped: o digest é calculado sem a própria assinatura
    digest = base64.b64encode(hashlib.sha256(_c14n(raiz)).digest()).decode()

    def sub(pai, tag, texto=None, **atributos):
        el = etree.SubElement(pai, f"{{{DS}}}{tag}", **atributos)
        el.text = texto
        return el

    assinatura = etree.SubElement(raiz, f"{{{DS}}}Signature", nsmap={None: DS})
    info = sub(assinatura, "SignedInfo")
    sub(info, "CanonicalizationMethod", Algorithm=C14N)
    sub(info, "SignatureMethod", Algorithm=RSA_SHA256)
    ref = sub(info, "Reference", URI="")
    transforms = sub(ref, "Transforms")
    sub(transforms, "Transform", Algorithm=ENVELOPED)
    sub(transforms, "Transform", Algorithm=C14N)
    sub(ref, "DigestMethod", Algorithm=SHA256)
    sub(ref, "DigestValue", digest)

    valor = certificado.chave.sign(_c14n(info), padding.PKCS1v15(), hashes.SHA256())
    sub(assinatura, "SignatureValue", base64.b64encode(valor).decode())
    x509data = sub(sub(assinatura, "KeyInfo"), "X509Data")
    der = certificado.cert.public_bytes(serialization.Encoding.DER)
    sub(x509data, "X509Certificate", base64.b64encode(der).decode())
    return etree.tostring(raiz, encoding="utf-8")


def pem_cliente(certificado: Certificado, senha_chave: bytes) -> tuple[bytes, bytes]:
    """Certificado e chave em PEM (chave cifrada) para a conexão TLS."""
    cert = certificado.cert.public_bytes(serialization.Encoding.PEM)
    chave = certificado.chave.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                            serialization.BestAvailableEncryption(senha_chave))
    return cert, chave
