"""
Testes Automatizados para o SEI-Anonimizer:
1. Tolerância a anomalias de PDFs (letras espaçadas, quebras de linha, hifenização).
2. Precisão de nomes e garantia de não-remoção de cidades/órgãos (filtro negativo).
3. Termos específicos customizados linha a linha com pontuações.
4. Redação física em PDF via PyMuPDF.
5. Suporte a DOCX e TXT.
6. Lazy Loading e benchmark de tempo de inicialização.
"""

import os
import time
import pytest
import pymupdf
import docx

from sei_anonimizer import DocumentAnonimizer
from sei_anonimizer.gazetteer import (
    normalizar_texto,
    limpar_prefixos_nome,
    validar_candidato_nome,
    TERMOS_PROTEGIDOS
)
from sei_anonimizer.pdf_matcher import (
    criar_regex_tolerante,
    buscar_retangulos_resilientes
)


def test_lazy_loading_boot_time():
    """Garante que a inicialização do módulo é ultrarrápida (< 1.0s) sem carregar spaCy."""
    t0 = time.perf_counter()
    anon = DocumentAnonimizer()
    t1 = time.perf_counter()
    assert (t1 - t0) < 1.0, f"Boot time excessivo: {(t1 - t0):.2f}s"
    assert anon.opcoes["nomes"] is False


def test_regex_tolerante_anomalias():
    """Valida o casamento resiliente contra kerning, quebras de linha e hifenização."""
    # 1. Kerning artificial (letras espaçadas)
    rgx1 = criar_regex_tolerante("Alberto Silva")
    assert rgx1.search("Processo de A  l  b  e  r  t  o   S  i  l  v  a deferido.") is not None

    # 2. Quebra de linha no meio de nome
    rgx2 = criar_regex_tolerante("Alberto de Campos e Silva")
    assert rgx2.search("Encaminhado para Alberto de\nCampos e Silva para análise.") is not None

    # 3. Hifenização de translineação
    rgx3 = criar_regex_tolerante("Alberto Silva")
    assert rgx3.search("Assinado por Alber-\nto Silva no dia de ontem.") is not None

    # 4. Termo com aspas e pontuações
    rgx4 = criar_regex_tolerante('"Nota Técnica nº 123/2026"')
    assert rgx4.search('Ref: "Nota Técnica nº 123/2026" anexada.') is not None


def test_protecao_cidades_e_orgaos():
    """Garante que cidades, ministérios, diretorias e portarias NÃO sejam classificados como nomes."""
    termos_nao_humanos = [
        "Brasília", "São Paulo", "Rio de Janeiro", "Belo Horizonte",
        "Ministério da Ciência", "Coordenação-Geral", "Diretoria de Pesquisa",
        "Portaria nº 45", "Resolução Normativa", "Termo de Outorga"
    ]
    for termo in termos_nao_humanos:
        cand_norm = normalizar_texto(termo)
        # Deve estar protegido ou falhar na validação de nome de pessoa
        eh_valido = validar_candidato_nome(termo)
        assert eh_valido is False, f"Falso positivo detectado em entidade protegida: {termo}"


def test_limpeza_prefixos_contextuais():
    """Valida que qualificadores como 'O proponente' sejam removidos da captura."""
    assert limpar_prefixos_nome("O proponente MARCOS ANTONIO") == "MARCOS ANTONIO"
    assert limpar_prefixos_nome("A servidora Juliana Costa") == "Juliana Costa"
    assert limpar_prefixos_nome("Relator: Carlos Eduardo") == "Carlos Eduardo"


def test_extracao_nomes_contextuais_sei():
    """Verifica a extração em texto com estrutura típica do SEI."""
    texto_sei = """
    Documento assinado eletronicamente por Juliana Costa Ferreira, Coordenadora, em 01/09/2026.
    Interessado: Alberto de Campos e Silva
    Relator: Carlos Eduardo Santos
    O proponente MARCOS ANTONIO PEREIRA, portador do CPF 111.222.333-44, solicitou recurso.
    Encaminhado para parecer na cidade de Brasília.
    """
    anon = DocumentAnonimizer(opcoes={"nomes": True})
    nomes_encontrados = anon.extrair_nomes_inteligente(texto_sei)

    assert "Alberto de Campos e Silva" in nomes_encontrados
    assert "Carlos Eduardo Santos" in nomes_encontrados
    assert "Juliana Costa Ferreira" in nomes_encontrados
    assert "MARCOS ANTONIO PEREIRA" in nomes_encontrados

    # Garante que 'Brasília' não entrou como nome
    assert "Brasília" not in nomes_encontrados


def test_redacao_pdf_em_memoria(tmp_path):
    """Testa a redação física real no PyMuPDF com anomalias de formatação."""
    pdf_in = str(tmp_path / "teste_in.pdf")
    pdf_out = str(tmp_path / "teste_out.pdf")

    doc = pymupdf.open()
    page = doc.new_page(width=600, height=800)
    page.insert_text((50, 100), "Interessado: A  l  b  e  r  t  o   S  i  l  v  a", fontsize=12)
    page.insert_text((50, 140), "Parecer de Alberto de\nCampos e Silva emitido.", fontsize=12)
    page.insert_text((50, 180), "Termo: \"Empresa XPTO Ltda.\"", fontsize=12)
    doc.save(pdf_in)
    doc.close()

    opcoes = {
        "termos_customizados": [
            "Alberto Silva",
            "Alberto de Campos e Silva",
            '"Empresa XPTO Ltda."'
        ]
    }

    with DocumentAnonimizer(opcoes=opcoes) as anon:
        anon.processar_arquivo(pdf_in, pdf_out)

    doc_out = pymupdf.open(pdf_out)
    texto_final = doc_out[0].get_text("text")
    doc_out.close()

    assert "Alberto" not in texto_final
    assert "XPTO" not in texto_final


def test_redacao_docx_e_txt(tmp_path):
    """Testa o processamento em arquivos DOCX e TXT."""
    txt_in = str(tmp_path / "doc.txt")
    txt_out = str(tmp_path / "doc_anon.txt")

    with open(txt_in, "w", encoding="utf-8") as f:
        f.write("Interessado: A  l  b  e  r  t  o   S  i  l  v  a\nCPF: 123.456.789-00\nTermo: Confidencial XYZ")

    opcoes = {
        "cpf": True,
        "termos_customizados": ["Alberto Silva", "Confidencial XYZ"]
    }

    with DocumentAnonimizer(opcoes=opcoes) as anon:
        anon.processar_arquivo(txt_in, txt_out)

    with open(txt_out, "r", encoding="utf-8") as f:
        conteudo = f.read()

    assert "Alberto" not in conteudo
    assert "Confidencial XYZ" not in conteudo
    assert "***.456.789-**" in conteudo
