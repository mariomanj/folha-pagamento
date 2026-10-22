"""Ponto de entrada do executável (interface gráfica).
FolhaPagamento.exe --autoteste grava autoteste.txt na pasta de dados e sai."""
import sys

if "--autoteste" in sys.argv:
    from folha.config import pasta_dados
    from folha.esocial.autoteste import executar

    (pasta_dados() / "autoteste.txt").write_text(executar(), encoding="utf-8")
else:
    from folha.gui import main

    main()
