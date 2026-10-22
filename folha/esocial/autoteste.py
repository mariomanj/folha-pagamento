"""Diagnóstico da instalação: gera, assina (certificado de teste) e valida um
evento de cada tipo com os esquemas embutidos. Não acessa a internet."""
from datetime import date
from decimal import Decimal as D

from ..calculo import Funcionario, calcular_folha
from . import assinatura, eventos as ev, validacao
from .rubricas import PADRAO


def executar() -> str:
    g = ev.Gerador(ev.Empregador("11222333000181", "11222333000181", "TESTE", "FOLHA", 2))
    f = Funcionario(nome="Teste", salario=D("3000"), cpf="52998224725", matricula_esocial="1")
    h = calcular_folha(f)
    casos = [("S-1010", g.s1010(PADRAO[0], "2026-01")),
             ("S-1200", g.s1200(f, "2026-01", [("T1", "mensal", h)], PADRAO)),
             ("S-1210", g.s1210(f.cpf, "2026-02", [(date(2026, 2, 5), "2026-01", "T1", h.liquido)])),
             ("S-1299", g.s1299("2026-01", True, True))]
    linhas, ok = [], True
    cert = assinatura.certificado_teste()
    for tipo, (_, xml) in casos:
        erros = validacao.erros(tipo, assinatura.assinar(xml, cert))
        ok &= not erros
        linhas.append(f"{tipo}: {'OK' if not erros else 'ERRO ' + '; '.join(erros[:2])}")
    raizes = (validacao.RECURSOS / "icp_brasil_raizes.pem").read_text(encoding="ascii").count("BEGIN CERTIFICATE")
    linhas.append(f"Raízes ICP-Brasil embutidas: {raizes}")
    linhas.append("RESULTADO: " + ("OK" if ok and raizes else "FALHOU"))
    return "\n".join(linhas)
