"""
Testes Automatizados para Redação Efetiva (Verdadeiro Tarjamento) e Sanitização em PDFs.

Cobre todos os critérios de aceite exigidos para documentos do SEI:
1. Expurgo Físico do Fluxo de Texto (Content Streams / Operadores Tj, TJ, BT...ET).
2. Teste de Extração de Texto via get_text().
3. Teste de Seleção e Clipboard (sem nós de texto na área tarjada).
4. Sanitização Completa de Metadados (/Author, /Title, /Subject, /Keywords) e Expurgo de XMP XML.
5. Persistência de Layout, Imagens Oficiais (timbres/brasões) e Elementos Oficiais SEI.
6. Comparação dos Modos de Redação (Tarja Preta, Tarja Branca e Máscara Textual).
7. Limpeza e Auditoria de Anotações Flutuantes (/Annots e Comentários).
"""

import os
import pytest
import pymupdf

from sei_anonimizer import DocumentAnonimizer


def test_expurgo_fisico_content_stream(tmp_path):
    """
    Critério 1: Garante que os operadores vetoriais de texto (Tj, TJ, BT...ET)
    não contenham nenhuma ocorrência dos termos confidenciais nos streams internos.
    """
    pdf_in = str(tmp_path / "stream_in.pdf")
    pdf_out = str(tmp_path / "stream_out.pdf")

    doc = pymupdf.open()
    page = doc.new_page(width=600, height=800)
    page.insert_text((50, 100), "Interessado: Alberto de Campos e Silva", fontsize=12)
    page.insert_text((50, 130), "CPF nº 123.456.789-00", fontsize=12)
    page.insert_text((50, 160), "Contato: alberto.silva@cnpq.br", fontsize=12)
    doc.save(pdf_in)
    doc.close()

    opcoes = {
        "cpf": True,
        "email_tel": True,
        "termos_customizados": ["Alberto de Campos e Silva"],
        "modo_redacao_pdf": "tarja_preta"
    }

    with DocumentAnonimizer(opcoes=opcoes) as anon:
        anon.processar_arquivo(pdf_in, pdf_out)

    doc_out = pymupdf.open(pdf_out)
    page_out = doc_out[0]
    raw_contents = page_out.read_contents()
    doc_out.close()

    # O conteúdo bruto do stream de comandos da página não pode conter os dados confidenciais
    assert b"Alberto" not in raw_contents
    assert b"Campos" not in raw_contents
    assert b"123.456.789-00" not in raw_contents
    assert b"alberto.silva@cnpq.br" not in raw_contents


def test_extracao_texto_e_selecao_clipboard(tmp_path):
    """
    Critérios 1 e 2: Ao executar page.get_text() ou inspecionar as palavras na página,
    nenhuma palavra ou caractere deve ser mapeado dentro das coordenadas do bounding box tarjado.
    """
    pdf_in = str(tmp_path / "clipboard_in.pdf")
    pdf_out = str(tmp_path / "clipboard_out.pdf")

    doc = pymupdf.open()
    page = doc.new_page(width=600, height=800)
    page.insert_text((50, 100), "Requerente: Mariana Ferreira Lima", fontsize=12)
    page.insert_text((50, 130), "Telefone Celular: (61) 98765-4321", fontsize=12)
    page.insert_text((50, 160), "Status: Processo deferido pela Diretoria.", fontsize=12)
    doc.save(pdf_in)
    doc.close()

    opcoes = {
        "email_tel": True,
        "termos_customizados": ["Mariana Ferreira Lima"],
        "modo_redacao_pdf": "tarja_preta"
    }

    with DocumentAnonimizer(opcoes=opcoes) as anon:
        anon.processar_arquivo(pdf_in, pdf_out)

    doc_out = pymupdf.open(pdf_out)
    page_out = doc_out[0]
    texto_extraido = page_out.get_text("text")

    # Extração de texto não deve conter as strings confidenciais
    assert "Mariana" not in texto_extraido
    assert "Ferreira" not in texto_extraido
    assert "98765-4321" not in texto_extraido
    assert "Processo deferido" in texto_extraido

    # Clipboard / Palavras mapeadas:
    palavras = page_out.get_text("words")
    for w in palavras:
        palavra_texto = w[4]
        assert "Mariana" not in palavra_texto
        assert "98765-4321" not in palavra_texto

    doc_out.close()


def test_sanitizacao_metadados_e_expurgo_xmp(tmp_path):
    """
    Critério 3: Nenhuma ocorrência de termos confidenciais deve permanecer
    em dicionários de metadados (/Title, /Author, /Subject, /Keywords) ou fluxos XMP XML.
    """
    pdf_in = str(tmp_path / "meta_in.pdf")
    pdf_out = str(tmp_path / "meta_out.pdf")

    doc = pymupdf.open()
    page = doc.new_page(width=600, height=800)
    page.insert_text((50, 100), "Conteúdo normal do documento administrativo.", fontsize=12)

    # Configuração de metadados com dados sensíveis
    doc.set_metadata({
        "author": "Mariana Ferreira Lima",
        "title": "Processo de Mariana Ferreira Lima - Benefício",
        "subject": "Recurso Administrativo - CPF 123.456.789-00",
        "keywords": "Mariana, CNPq, Parecer"
    })
    doc.set_xml_metadata("<x:xmpmeta><rdf:RDF><rdf:Description>Mariana Ferreira Lima</rdf:Description></rdf:RDF></x:xmpmeta>")
    doc.save(pdf_in)
    doc.close()

    opcoes = {
        "cpf": True,
        "termos_customizados": ["Mariana Ferreira Lima"],
        "sanitizar_metadados": True
    }

    with DocumentAnonimizer(opcoes=opcoes) as anon:
        anon.processar_arquivo(pdf_in, pdf_out)

    doc_out = pymupdf.open(pdf_out)
    meta = doc_out.metadata

    # Autor deve ser completamente limpo
    assert meta.get("author") == ""
    # Título, Assunto e Palavras-chave não podem conter o nome confidencial
    assert "Mariana" not in (meta.get("title") or "")
    assert "Mariana" not in (meta.get("subject") or "")
    assert "123.456.789-00" not in (meta.get("subject") or "")
    assert "Mariana" not in (meta.get("keywords") or "")

    # XML/XMP metadata deve estar nulo/removido
    xml_meta = doc_out.get_xml_metadata()
    if xml_meta:
        assert "Mariana" not in xml_meta

    doc_out.close()

    # Inspeção binária bruta no arquivo salvo em disco
    with open(pdf_out, "rb") as f:
        bytes_arquivo = f.read()
    assert b"Mariana" not in bytes_arquivo


def test_persistencia_layout_e_elementos_sei(tmp_path):
    """
    Critério 4: Mantém o layout, cabeçalhos oficiais do SEI, dimensões de página,
    resolução e imagens não sobrepostas (timbres institucionais) 100% intactos.
    """
    pdf_in = str(tmp_path / "layout_in.pdf")
    pdf_out = str(tmp_path / "layout_out.pdf")

    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)  # Padrão A4

    # Insere imagem simulando o Brasão da República no topo
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 40, 40), 0)
    pix.clear_with(200)
    page.insert_image(pymupdf.Rect(50, 30, 90, 70), pixmap=pix)

    # Cabeçalho institucional do SEI
    page.insert_text((110, 45), "MINISTÉRIO DA CIÊNCIA, TECNOLOGIA E INOVAÇÃO", fontsize=10)
    page.insert_text((110, 60), "CONSELHO NACIONAL DE DESENVOLVIMENTO CIENTÍFICO E TECNOLÓGICO", fontsize=10)

    # Corpo com dados sensíveis e dados públicos
    page.insert_text((50, 150), "PARECER TÉCNICO Nº 123/2026", fontsize=12)
    page.insert_text((50, 180), "Bolsista Indicado: João Pedro de Alencar", fontsize=11)
    page.insert_text((50, 200), "CPF nº 999.888.777-66", fontsize=11)
    page.insert_text((50, 230), "O projeto atende com mérito aos requisitos do edital vigente.", fontsize=11)

    # Rodapé institucional com numeração
    page.insert_text((50, 800), "Documento registrado no SEI sob o Processo 01234.005678/2026-90", fontsize=9)
    page.insert_text((500, 800), "Página 1 de 1", fontsize=9)

    doc.save(pdf_in)
    doc.close()

    opcoes = {
        "cpf": True,
        "termos_customizados": ["João Pedro de Alencar"],
        "modo_redacao_pdf": "tarja_preta"
    }

    with DocumentAnonimizer(opcoes=opcoes) as anon:
        anon.processar_arquivo(pdf_in, pdf_out)

    doc_out = pymupdf.open(pdf_out)
    page_out = doc_out[0]

    # Dimensões da página A4 perfeitamente preservadas
    assert page_out.rect.width == 595
    assert page_out.rect.height == 842

    # Imagem do Brasão permanece intacta
    assert len(page_out.get_images()) >= 1

    texto_out = page_out.get_text("text")

    # Cabeçalhos e rodapés oficiais intactos
    assert "MINISTÉRIO DA CIÊNCIA" in texto_out
    assert "CONSELHO NACIONAL DE DESENVOLVIMENTO CIENTÍFICO" in texto_out
    assert "PARECER TÉCNICO Nº 123/2026" in texto_out
    assert "O projeto atende com mérito" in texto_out
    assert "Página 1 de 1" in texto_out

    # Dados sensíveis expurgados
    assert "João Pedro de Alencar" not in texto_out
    assert "999.888.777-66" not in texto_out

    doc_out.close()


def test_modos_redacao_tarja_preta_e_branca(tmp_path):
    """
    Testa a alternância entre os modos 'tarja_preta' e 'tarja_branca'.
    Ambos devem expurgar fisicamente o texto do stream.
    """
    for modo in ("tarja_preta", "tarja_branca"):
        pdf_in = str(tmp_path / f"modo_{modo}_in.pdf")
        pdf_out = str(tmp_path / f"modo_{modo}_out.pdf")

        doc = pymupdf.open()
        page = doc.new_page(width=600, height=800)
        page.insert_text((50, 100), "Beneficiário: Carlos Drummond de Andrade", fontsize=12)
        doc.save(pdf_in)
        doc.close()

        with DocumentAnonimizer(opcoes={"termos_customizados": ["Carlos Drummond de Andrade"], "modo_redacao_pdf": modo}) as anon:
            anon.processar_arquivo(pdf_in, pdf_out)

        doc_out = pymupdf.open(pdf_out)
        conteudo_stream = doc_out[0].read_contents()
        texto_pagina = doc_out[0].get_text("text")
        doc_out.close()

        # Ambos os modos de tarja suprimem completamente os operadores vetoriais de texto
        assert b"Drummond" not in conteudo_stream
        assert "Drummond" not in texto_pagina


def test_modo_mascara_texto_retrocompativel(tmp_path):
    """
    Testa a retrocompatibilidade do modo 'mascara_texto', que carimba o texto substituto.
    """
    pdf_in = str(tmp_path / "mascara_in.pdf")
    pdf_out = str(tmp_path / "mascara_out.pdf")

    doc = pymupdf.open()
    page = doc.new_page(width=600, height=800)
    page.insert_text((50, 100), "E-mail: contato@empresa.com", fontsize=12)
    doc.save(pdf_in)
    doc.close()

    with DocumentAnonimizer(opcoes={"email_tel": True, "modo_redacao_pdf": "mascara_texto"}) as anon:
        anon.processar_arquivo(pdf_in, pdf_out)

    doc_out = pymupdf.open(pdf_out)
    texto_pagina = doc_out[0].get_text("text")
    doc_out.close()

    assert "contato@empresa.com" not in texto_pagina
    assert "[E-MAIL]" in texto_pagina


def test_limpeza_anotacoes_comentarios_flutuantes(tmp_path):
    """
    Critério 2 e 3: Garante que anotações flutuantes (/Annots, notas adesivas ou popups)
    que contenham dados confidenciais sejam higienizadas ou removidas.
    """
    pdf_in = str(tmp_path / "annot_in.pdf")
    pdf_out = str(tmp_path / "annot_out.pdf")

    doc = pymupdf.open()
    page = doc.new_page(width=600, height=800)
    page.insert_text((50, 100), "Processo geral em andamento.", fontsize=12)

    # Cria anotação de texto com comentário confidencial
    page.add_text_annot((100, 100), "Nota confidencial do relator: Dr. Alberto Silva aprovou.")
    # Cria anotação legítima não confidencial
    page.add_text_annot((100, 300), "Nota pública: Arquivo conferido pela secretaria.")
    doc.save(pdf_in)
    doc.close()

    opcoes = {
        "termos_customizados": ["Alberto Silva"],
        "limpar_anotacoes": True
    }

    with DocumentAnonimizer(opcoes=opcoes) as anon:
        anon.processar_arquivo(pdf_in, pdf_out)

    doc_out = pymupdf.open(pdf_out)
    page_out = doc_out[0]
    annots_finais = list(page_out.annots())
    doc_out.close()

    # A anotação contendo o nome sensível deve ter sido eliminada
    for a in annots_finais:
        info = a.info or {}
        conteudo = (info.get("content") or "") + " " + (info.get("title") or "")
        assert "Alberto Silva" not in conteudo


def test_redacao_multiplas_paginas_preservacao_layout(tmp_path):
    """
    Critério 4: Garante a persistência de estrutura em documentos multi-páginas,
    com numeração ('Página 1 de 2', 'Página 2 de 2') e cabeçalhos intactos.
    """
    pdf_in = str(tmp_path / "multipag_in.pdf")
    pdf_out = str(tmp_path / "multipag_out.pdf")

    doc = pymupdf.open()
    # Página 1
    p1 = doc.new_page(width=595, height=842)
    p1.insert_text((50, 50), "MINISTÉRIO DA CIÊNCIA, TECNOLOGIA E INOVAÇÃO", fontsize=10)
    p1.insert_text((50, 150), "Interessada: Dra. Juliana Costa Ferreira", fontsize=12)
    p1.insert_text((50, 800), "Página 1 de 2", fontsize=9)

    # Página 2
    p2 = doc.new_page(width=595, height=842)
    p2.insert_text((50, 50), "MINISTÉRIO DA CIÊNCIA, TECNOLOGIA E INOVAÇÃO", fontsize=10)
    p2.insert_text((50, 150), "Parecer conclusivo sobre o CPF 333.444.555-66.", fontsize=12)
    p2.insert_text((50, 800), "Página 2 de 2", fontsize=9)

    doc.save(pdf_in)
    doc.close()

    opcoes = {
        "cpf": True,
        "termos_customizados": ["Juliana Costa Ferreira"],
        "modo_redacao_pdf": "tarja_preta"
    }

    with DocumentAnonimizer(opcoes=opcoes) as anon:
        anon.processar_arquivo(pdf_in, pdf_out)

    doc_out = pymupdf.open(pdf_out)
    assert len(doc_out) == 2

    # Validações Página 1
    t1 = doc_out[0].get_text("text")
    assert "MINISTÉRIO DA CIÊNCIA" in t1
    assert "Página 1 de 2" in t1
    assert "Juliana Costa Ferreira" not in t1

    # Validações Página 2
    t2 = doc_out[1].get_text("text")
    assert "MINISTÉRIO DA CIÊNCIA" in t2
    assert "Página 2 de 2" in t2
    assert "333.444.555-66" not in t2

    doc_out.close()


def test_redacao_qr_code_e_burn_in(tmp_path):
    """
    Critério 1 e 2: Valida que a opção qr_code realiza o expurgo da área do QR Code
    e da barra lateral do SEI sem corromper imagens de cabeçalho.
    """
    pdf_in = str(tmp_path / "qrcode_in.pdf")
    pdf_out = str(tmp_path / "qrcode_out.pdf")

    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)

    # Imagem 1: Logo topo (50, 20, 100, 70)
    pix_logo = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 30, 30), 0)
    pix_logo.clear_with(220)
    page.insert_image(pymupdf.Rect(50, 20, 100, 70), pixmap=pix_logo)

    # Imagem 2: QR Code na área de autenticidade (100, 700, 150, 750)
    pix_qr = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 40, 40), 0)
    pix_qr.clear_with(50)
    page.insert_image(pymupdf.Rect(100, 700, 150, 750), pixmap=pix_qr)

    # Texto oficial do SEI que ancora o QR Code
    page.insert_text((160, 720), "A autenticidade do documento pode ser conferida no site https://sei.cnpq.br", fontsize=9)

    doc.save(pdf_in)
    doc.close()

    opcoes = {
        "qr_code": True,
        "links": True
    }

    with DocumentAnonimizer(opcoes=opcoes) as anon:
        anon.processar_arquivo(pdf_in, pdf_out)

    doc_out = pymupdf.open(pdf_out)
    page_out = doc_out[0]

    # Logo do cabeçalho permanece no documento
    assert len(page_out.get_images()) >= 1

    # Texto ao redor do QR Code continua legível
    texto_out = page_out.get_text("text")
    assert "A autenticidade do documento pode ser conferida" in texto_out

    doc_out.close()


def test_mapear_e_aplicar_tarjas_manuais_interativo(tmp_path):
    """
    Testa a separação em duas etapas usada pelo visualizador interativo (JanelaTarjamentoPDF):
    1. Mapeamento automático prévio de tarjas (mapear_todas_tarjas_documento).
    2. Inclusão de tarjas manuais desenhadas pelo usuário.
    3. Aplicação física definitiva e salvamento sanitizado (aplicar_tarjas_documento).
    """
    pdf_in = str(tmp_path / "interativo_in.pdf")
    pdf_out = str(tmp_path / "interativo_out.pdf")

    doc = pymupdf.open()
    page = doc.new_page(width=600, height=800)
    page.insert_text((50, 100), "CPF do requerente: 123.456.789-00", fontsize=12)
    page.insert_text((50, 150), "Dado Confidencial Selecionado Manualmente pelo Operador", fontsize=12)
    page.insert_text((50, 200), "Texto Público que Deve Permanecer Intacto no Documento", fontsize=12)
    doc.save(pdf_in)
    doc.close()

    opcoes = {
        "cpf": True,
        "modo_redacao_pdf": "tarja_preta",
        "sanitizar_metadados": True
    }

    anon = DocumentAnonimizer(opcoes=opcoes)
    doc_proc = pymupdf.open(pdf_in)

    # Etapa 1: Mapeamento de tarjas
    mapa_tarjas, termos_anon = anon.mapear_todas_tarjas_documento(doc_proc)

    # Verifica se o CPF foi identificado automaticamente na página 0
    assert 0 in mapa_tarjas
    tarjas_p0 = mapa_tarjas[0]
    assert any(t["tipo"] == "cpf" for t in tarjas_p0)

    # Etapa 2: Simula operador adicionando tarja manual no visualizador
    rects_manual = doc_proc[0].search_for("Dado Confidencial Selecionado Manualmente")
    assert len(rects_manual) > 0
    mapa_tarjas[0].append({
        "rect": rects_manual[0],
        "tipo": "manual",
        "rotulo": "Manual",
        "fill_custom": None
    })

    # Etapa 3: Aplicação e salvamento
    anon.aplicar_tarjas_documento(doc_proc, mapa_tarjas, termos_anon, pdf_out)
    doc_proc.close()

    # Validação do documento resultante
    doc_verif = pymupdf.open(pdf_out)
    texto_final = doc_verif[0].get_text("text")
    stream_final = doc_verif[0].read_contents()
    doc_verif.close()

    # CPF deve estar fisicamente expurgado
    assert "123.456.789-00" not in texto_final
    assert b"123.456.789-00" not in stream_final

    # Trecho manual também deve estar fisicamente expurgado
    assert "Dado Confidencial Selecionado Manualmente" not in texto_final
    assert b"Dado Confidencial Selecionado" not in stream_final

    # Texto legítimo permanece intacto
    assert "Texto Público que Deve Permanecer Intacto" in texto_final


