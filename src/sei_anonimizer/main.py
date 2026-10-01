"""
Módulo Principal do SEI-Anonimizer.

Contém:
1. DocumentAnonimizer: Classe central para anonimização estruturada e contextual de documentos
   (.pdf, .docx, .txt), com suporte a documentos do SEI, CPF, RG, contatos, QR Codes, links,
   detecção de nomes de alta precisão e termos específicos personalizados.
2. AppAnonimizer / iniciar_interface_grafica: Interface gráfica persistente, moderna e High-DPI.
"""

import os
import re
import sys
import logging
import threading
from typing import Dict, List, Set, Optional, Tuple, Any
from importlib.metadata import version, PackageNotFoundError

# Garante resolução do pacote raiz quando executado standalone ou compilado via Nuitka
_pkg_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _pkg_root not in sys.path:
    sys.path.insert(0, _pkg_root)

# pymupdf e docx são importados sob demanda (lazy loading)
try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk, scrolledtext
except (ImportError, ModuleNotFoundError):
    tk = None
    filedialog = None
    messagebox = None
    ttk = None
    scrolledtext = None

docx = None  # Carregado sob demanda em _processar_docx

try:
    __version__ = version("sei_anonimizer")
except PackageNotFoundError:
    __version__ = "1.1.0"

# Importa módulos internos especializados
from sei_anonimizer.gazetteer import (
    TERMOS_PROTEGIDOS,
    limpar_prefixos_nome,
    validar_candidato_nome,
    normalizar_texto
)
from sei_anonimizer.pdf_matcher import (
    criar_regex_tolerante,
    buscar_retangulos_resilientes
)

# Configuração de logger
logger = logging.getLogger("sei_anonimizer")
logger.setLevel(logging.INFO)
if not logger.handlers:
    _handler = logging.StreamHandler()
    _formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    _handler.setFormatter(_formatter)
    logger.addHandler(_handler)

# Singleton para Lazy Loading do spaCy (carregado apenas sob demanda se 'nomes' estiver ativo)
_nlp_spacy_cache = None
_spacy_carregado_tentativa = False


def obter_modelo_nlp():
    """
    Carrega o modelo spaCy (pt_core_news_lg) de forma estritamente sob demanda (Lazy Loading).
    Evita qualquer overhead de boot ou consumo de memória quando 'nomes' não for utilizado.
    """
    global _nlp_spacy_cache, _spacy_carregado_tentativa
    if _nlp_spacy_cache is not None:
        return _nlp_spacy_cache

    if _spacy_carregado_tentativa:
        return None

    _spacy_carregado_tentativa = True
    try:
        import spacy
        logger.info("Carregando modelo spaCy (pt_core_news_lg) sob demanda...")
        _nlp_spacy_cache = spacy.load("pt_core_news_lg", disable=["lemmatizer", "textcat", "custom"])
        logger.info("Modelo spaCy carregado com sucesso.")
    except Exception as e:
        logger.warning(f"spaCy ou modelo pt_core_news_lg não disponível no ambiente: {e}")
        _nlp_spacy_cache = None

    return _nlp_spacy_cache


class DocumentAnonimizer:
    """
    Motor de anonimização com processamento tolerante a falhas em PDFs, DOCX e TXT.
    
    Opções suportadas:
        cpf (bool): Mascarar CPFs (***.123.456-**). Padrão: True.
        rg (bool): Mascarar RGs e datas de expedição. Padrão: True.
        email_tel (bool): Mascarar e-mails e telefones. Padrão: True.
        doc_sei (bool): Mascarar números de documento e verificador do SEI. Padrão: True.
        qr_code (bool): Mascarar QR Code e barra lateral do SEI em PDFs. Padrão: True.
        links (bool): Remover links clicáveis em PDFs. Padrão: True.
        nomes (bool): Mascarar nomes próprios via heurísticas contextuais e NLP. Padrão: False.
        modo_nomes (str): "iniciais" (ex: A. C. S.) ou "total" ([NOME]). Padrão: "iniciais".
        termos_customizados (list): Lista de termos específicos adicionais digitados pelo usuário.
    """

    REGEX_CPF = re.compile(r'\b\d{3}\.\d{3}\.\d{3}-\d{2}\b')
    REGEX_CPF_DESFORMATADO = re.compile(r'(?i:\bCPF\b\s*(?:n[º°.]?|:\s*)?)\s*(\b\d{11}\b)')
    REGEX_RG_CONTEXTO = re.compile(r'(?i:\b(?:RG|Identidade)\b\s*(?:n[º°.]?|:\s*)?)\s*([0-9A-Za-z.-]+\s?[0-9A-Za-z]*)')
    REGEX_DATA_EXP = re.compile(r'(Data de Expedição:)\s*(\d{2}/\d{2}/\d{4})', re.IGNORECASE)
    REGEX_7_DIGITOS = re.compile(r'\b\d{7}\b')
    REGEX_CRC = re.compile(r'\b[0-9A-F]{8}\b', re.IGNORECASE)
    REGEX_EMAIL = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b')
    REGEX_TELEFONE = re.compile(r'(?:\+55\s*)?(?:\(?\d{2}\)?\s*)?(?:9\d{4}|\d{4})[-\s]\d{4}\b')

    @staticmethod
    def _eh_telefone_valido(texto_completo: str, start: int, end: int, fone_str: str) -> bool:
        digitos = re.sub(r'\D', '', fone_str)
        fone_limpo = fone_str.strip()
        if fone_limpo.startswith(('0800', '0300', '(0800', '(0300', '+55 0800', '+55 (0800')):
            return False
        if digitos.startswith(('0800', '0300', '550800', '550300')):
            return False

        trecho_anterior = texto_completo[max(0, start - 25):start]
        if re.search(r'R\$\s*$', trecho_anterior, re.IGNORECASE):
            return False
        if re.search(r'(?:Chamada|Edital|Portaria|Processo|Parecer|Acórdão|Lei|Decreto)\s+(?:n[º°.]?\s*)?$', trecho_anterior, re.IGNORECASE):
            return False

        if re.match(r'^(?:19|20)\d{2}[-\s](?:19|20)\d{2}$', fone_limpo):
            return False

        trecho_amplo = texto_completo[max(0, start - 10):min(len(texto_completo), end + 10)]
        if re.search(r'\d{1,4}[/-]\d{1,2}[/-]\d{2,4}', trecho_amplo):
            return False
        if '/' in trecho_amplo:
            return False

        if len(digitos) in (8, 9, 10, 11, 12, 13):
            if len(digitos) == 8 and digitos.startswith(('19', '20')):
                return False
            return True
        return False

    # Padrões contextuais administrativos / SEI de altíssima precisão
    PADROES_CONTEXTUAIS = [
        re.compile(r'assinado\s+eletronicamente\s+por\s+([A-ZÀ-Ÿa-zà-ÿ\s]+?)(?:,|\n|\r|em\s+\d|\s*–|\s*-|\.|$)', re.IGNORECASE),
        re.compile(r'(?:Interessad[oa]|Requerente|Relator(?:a)?|Coordenador(?:a)?|Servidor(?:a)?|Bolsista|Proponente|Membro|Pesquisador(?:a)?|Orientador(?:a)?)\s*:\s*([^\n\r,.;\(\)–-]+)', re.IGNORECASE),
        re.compile(r'([A-ZÀ-Ÿa-zà-ÿ][^\n\r,.;\(\)–-]+?)(?:,\s*portador(?:a)?\s*do\s*CPF|,\s*CPF\s*nº|,\s*matrícula|,\s*SIAPE)', re.IGNORECASE),
        re.compile(r'(?:Prof\.|Profa\.|Professora?|Dr\.|Dra\.|Doutora?|Sr\.|Sra\.|Senhora?)\s+([^\n\r,.;\(\)–-]+)', re.IGNORECASE),
        re.compile(r'À\s+consideração\s+d[eoa]\s+([^\n\r,.;\(\)–-]+)', re.IGNORECASE)
    ]

    # Expressões morfológicas para candidatos a nomes próprios
    REGEX_NOME_CAPS = re.compile(r'\b[A-ZÀ-Ÿ]{2,}(?: (?:DE|DA|DO|DOS|DAS|E) )?(?: [A-ZÀ-Ÿ]{2,}){1,4}\b')
    REGEX_NOME_TITLE = re.compile(r'\b[A-ZÀ-Ÿ][a-zà-ÿ]+(?: (?:de|da|do|dos|das|e) )?(?: [A-ZÀ-Ÿ][a-zà-ÿ]+){1,4}\b')

    def __init__(self, opcoes: Optional[Dict[str, any]] = None):
        self.opcoes = {
            "cpf": True,
            "rg": True,
            "email_tel": True,
            "doc_sei": True,
            "qr_code": True,
            "links": True,
            "nomes": False,
            "modo_nomes": "iniciais",
            "termos_customizados": []
        }
        if opcoes:
            self.opcoes.update(opcoes)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    @staticmethod
    def mascarar_cpf_fmt(cpf_original: str) -> str:
        numeros = re.sub(r'\D', '', cpf_original)
        if len(numeros) == 11:
            return f"***.{numeros[3:6]}.{numeros[6:9]}-**"
        return "***.***.***-**"

    @staticmethod
    def mascarar_doc_7_digitos_fmt(numero: str) -> str:
        if len(numero) == 7:
            return "XXXXX" + numero[-2:]
        return "XXXXXXX"

    def _gerar_iniciais(self, nome_completo: str) -> str:
        palavras = nome_completo.split()
        iniciais = []
        stopwords = {"DE", "DA", "DO", "DAS", "DOS", "E"}

        for p in palavras:
            p_upper = normalizar_texto(p)
            if p_upper in stopwords:
                continue

            if len(p) <= 2 and (p.endswith('.') or p.isupper()):
                iniciais.append(p if p.endswith('.') else p + ".")
            elif len(p) > 1:
                iniciais.append(p[0].upper() + ".")

        return " ".join(iniciais) if iniciais else "[N.I.]"

    def extrair_nomes_inteligente(self, texto: str) -> Set[str]:
        """
        Extrai nomes próprios de pessoas através de arquitetura multi-camadas:
        1. Âncoras contextuais de atos administrativos e do SEI.
        2. Validação morfológica com gazetteer curado de primeiros nomes do Brasil.
        3. spaCy sob demanda (se ativado nas opções e disponível).
        4. Filtro negativo estrito de termos institucionais e cidades protegidas.
        """
        if not texto or not texto.strip():
            return set()

        candidatos = set()

        # Camada 1: Âncoras contextuais SEI
        for padrao in self.PADROES_CONTEXTUAIS:
            for match in padrao.finditer(texto):
                captura = match.group(1)
                nome = limpar_prefixos_nome(captura)
                if len(nome.split()) >= 2 and len(nome) > 4:
                    candidatos.add(nome)

        # Camada 2: Validação morfológica (Caixa Alta e Title Case)
        for rgx in [self.REGEX_NOME_CAPS, self.REGEX_NOME_TITLE]:
            for match in rgx.finditer(texto):
                cand = " ".join(match.group(0).split())
                if validar_candidato_nome(cand):
                    candidatos.add(cand)

        # Camada 3: Reconhecimento Estatístico via spaCy (Lazy Loaded)
        if self.opcoes.get("nomes"):
            nlp = obter_modelo_nlp()
            if nlp:
                try:
                    # Avalia o texto ou blocos
                    doc = nlp(texto[:100000])  # Limite de segurança por bloco
                    for ent in doc.ents:
                        if ent.label_ == "PER":
                            nome_ent = " ".join(ent.text.replace("\n", " ").split())
                            nome_limpo = limpar_prefixos_nome(nome_ent)
                            if len(nome_limpo.split()) >= 2 and len(nome_limpo) > 4:
                                candidatos.add(nome_limpo)
                except Exception as e:
                    logger.debug(f"Processamento spaCy ignorado para trecho: {e}")

        # Camada 4: Filtro Negativo Rigoroso (Blacklist de Proteção)
        nomes_validados = set()
        for cand in candidatos:
            cand_norm = normalizar_texto(cand)
            if cand_norm in TERMOS_PROTEGIDOS:
                continue
            # Verifica se contém palavras exclusivas de entidades não-humanas
            palavras_proibidas = {
                "MINISTERIO", "COORDENACAO", "DIRETORIA", "UNIVERSIDADE", "INSTITUTO",
                "PORTARIA", "RESOLUCAO", "EDITAL", "PROCESSO", "TRIBUNAL", "GOVERNO"
            }
            if set(cand_norm.split()).intersection(palavras_proibidas):
                continue
            nomes_validados.add(cand)

        return nomes_validados

    def processar_arquivo(self, caminho_entrada: str, caminho_saida: Optional[str] = None) -> str:
        """
        Roteia o processamento do arquivo de acordo com a sua extensão (.pdf, .docx, .txt).
        """
        if not os.path.exists(caminho_entrada):
            raise FileNotFoundError(f"Arquivo não localizado: {caminho_entrada}")

        extensao = caminho_entrada.lower().split('.')[-1]

        if not caminho_saida:
            pasta_pai = os.path.dirname(caminho_entrada)
            nome_arquivo = os.path.basename(caminho_entrada)
            caminho_saida = os.path.join(pasta_pai, os.path.splitext(nome_arquivo)[0] + f"_anonimizado.{extensao}")

        logger.info(f"Iniciando anonimização: {os.path.basename(caminho_entrada)}")

        if extensao == 'pdf':
            return self._processar_pdf(caminho_entrada, caminho_saida)
        elif extensao == 'txt':
            return self._processar_txt(caminho_entrada, caminho_saida)
        elif extensao == 'docx':
            return self._processar_docx(caminho_entrada, caminho_saida)
        else:
            raise ValueError(f"Formato de arquivo não suportado: .{extensao}")

    def _aplicar_substituicoes_texto(self, texto: str) -> str:
        """
        Aplica regras de substituição textual direta para DOCX e TXT.
        """
        if not texto or not texto.strip():
            return texto

        # 1. Termos específicos customizados do usuário
        termos_custom = self.opcoes.get("termos_customizados") or []
        for t in termos_custom:
            if t and t.strip():
                rgx = criar_regex_tolerante(t)
                if rgx:
                    texto = rgx.sub("[REMOVIDO]", texto)

        # 2. Nomes próprios inteligentes
        if self.opcoes.get("nomes"):
            nomes = self.extrair_nomes_inteligente(texto)
            for nome in sorted(nomes, key=len, reverse=True):
                substituto = self._gerar_iniciais(nome) if self.opcoes.get("modo_nomes") == "iniciais" else "[NOME]"
                rgx_nome = criar_regex_tolerante(nome)
                if rgx_nome:
                    texto = rgx_nome.sub(substituto, texto)

        # 3. E-mails e Telefones
        if self.opcoes.get("email_tel"):
            texto = self.REGEX_EMAIL.sub("[E-MAIL]", texto)

            def repl_tel(m):
                fone = m.group()
                start = m.start()
                end = m.end()
                if not self._eh_telefone_valido(texto, start, end, fone):
                    return fone
                return "[TEL]"

            texto = self.REGEX_TELEFONE.sub(repl_tel, texto)

        # 4. CPF
        if self.opcoes.get("cpf"):
            texto = self.REGEX_CPF.sub(lambda m: self.mascarar_cpf_fmt(m.group()), texto)

            def repl_cpf_desfmt(m):
                texto_todo = m.group(0)
                cpf_digitos = m.group(1)
                idx = texto_todo.rfind(cpf_digitos)
                return texto_todo[:idx] + self.mascarar_cpf_fmt(cpf_digitos) + texto_todo[idx + len(cpf_digitos):]

            texto = self.REGEX_CPF_DESFORMATADO.sub(repl_cpf_desfmt, texto)

        # 5. RG e Data de Expedição
        if self.opcoes.get("rg"):
            def repl_rg(m):
                texto_todo = m.group(0)
                rg_valor = m.group(1).strip()
                if not rg_valor:
                    return texto_todo
                idx = texto_todo.rfind(rg_valor)
                return texto_todo[:idx] + "XXXXXX" + texto_todo[idx + len(rg_valor):]

            texto = self.REGEX_RG_CONTEXTO.sub(repl_rg, texto)
            texto = self.REGEX_DATA_EXP.sub(r'\1 XX/XX/XXXX', texto)

        # 6. Documento SEI
        if self.opcoes.get("doc_sei"):
            texto = self.REGEX_7_DIGITOS.sub(lambda m: self.mascarar_doc_7_digitos_fmt(m.group()), texto)
            texto = self.REGEX_CRC.sub("XXXXXXXX", texto)

        return texto

    def _processar_txt(self, caminho_entrada: str, caminho_saida: str) -> str:
        try:
            with open(caminho_entrada, 'r', encoding='utf-8', errors='replace') as f:
                texto = f.read()

            texto_anonimizado = self._aplicar_substituicoes_texto(texto)

            with open(caminho_saida, 'w', encoding='utf-8') as f:
                f.write(texto_anonimizado)
            return caminho_saida
        except Exception as e:
            logger.error(f"Falha de processamento TXT em {caminho_entrada}: {e}", exc_info=True)
            raise

    def _processar_docx(self, caminho_entrada: str, caminho_saida: str) -> str:
        try:
            try:
                import docx
            except (ImportError, ModuleNotFoundError):
                raise ImportError(
                    "A biblioteca python-docx não está instalada. "
                    "Instale com: uv add \"sei-anonimizer[arquivos]\" ou pip install python-docx"
                )

            documento = docx.Document(caminho_entrada)

            for p in documento.paragraphs:
                if p.text:
                    p.text = self._aplicar_substituicoes_texto(p.text)

            for table in documento.tables:
                for row in table.rows:
                    for cell in row.cells:
                        for p in cell.paragraphs:
                            if p.text:
                                p.text = self._aplicar_substituicoes_texto(p.text)

            documento.save(caminho_saida)
            return caminho_saida
        except Exception as e:
            logger.error(f"Falha de processamento DOCX em {caminho_entrada}: {e}", exc_info=True)
            raise

    def _processar_pdf(self, caminho_entrada: str, caminho_saida: str) -> str:
        doc = None
        try:
            try:
                import pymupdf
            except (ImportError, ModuleNotFoundError):
                raise ImportError(
                    "A biblioteca pymupdf não está instalada. "
                    "Instale com: uv add \"sei-anonimizer[arquivos]\" ou pip install pymupdf"
                )

            doc = pymupdf.open(caminho_entrada)
            if doc.is_encrypted:
                logger.warning(f"O documento {caminho_entrada} está protegido por senha. Ignorando.")
                raise PermissionError("Arquivo PDF protegido por senha.")

            termos_custom = self.opcoes.get("termos_customizados") or []

            for page in doc:
                texto_pagina = page.get_text("text")
                altura_pagina = page.rect.height
                largura_pagina = page.rect.width

                # 1. Remoção de links
                if self.opcoes.get("links"):
                    if hasattr(page, "delete_links"):
                        page.delete_links()
                    else:
                        for link in page.get_links():
                            page.delete_link(link)

                # 2. Tarjas de QR Code e Barra Lateral SEI
                if self.opcoes.get("qr_code"):
                    rect_barra = pymupdf.Rect(largura_pagina - 25, 0, largura_pagina, altura_pagina)
                    annot = page.add_redact_annot(rect_barra, fill=(0, 0, 0))
                    annot.update()

                    areas_auth = page.search_for("A autenticidade do documento pode ser conferida no site")
                    if areas_auth:
                        for area in areas_auth:
                            rect_qr = pymupdf.Rect(area.x0 - 60, area.y0 - 10, area.x0, area.y1 + 40)
                            annot = page.add_redact_annot(rect_qr, fill=(1, 1, 1))
                            annot.update()

                # 3. E-mails e Telefones
                if self.opcoes.get("email_tel"):
                    for match in self.REGEX_EMAIL.finditer(texto_pagina):
                        for area in page.search_for(match.group()):
                            tam = max(round(area.height * 0.75, 1), 6)
                            annot = page.add_redact_annot(area, text="[E-MAIL]", fontname="Helvetica", fontsize=tam, fill=(1, 1, 1))
                            annot.update()

                    for match in self.REGEX_TELEFONE.finditer(texto_pagina):
                        fone = match.group()
                        if not self._eh_telefone_valido(texto_pagina, match.start(), match.end(), fone):
                            continue
                        for area in page.search_for(fone):
                            tam = max(round(area.height * 0.75, 1), 6)
                            annot = page.add_redact_annot(area, text="[TEL]", fontname="Helvetica", fontsize=tam, fill=(1, 1, 1))
                            annot.update()

                # 4. CPF
                if self.opcoes.get("cpf"):
                    for match in self.REGEX_CPF.finditer(texto_pagina):
                        cpf = match.group()
                        mascara = self.mascarar_cpf_fmt(cpf)
                        for area in page.search_for(cpf):
                            tam = max(round(area.height * 0.75, 1), 6)
                            annot = page.add_redact_annot(area, text=mascara, fontname="Helvetica", fontsize=tam, fill=(1, 1, 1))
                            annot.update()

                    for match in self.REGEX_CPF_DESFORMATADO.finditer(texto_pagina):
                        cpf_digitos = match.group(1)
                        mascara = self.mascarar_cpf_fmt(cpf_digitos)
                        for area in page.search_for(cpf_digitos):
                            tam = max(round(area.height * 0.75, 1), 6)
                            annot = page.add_redact_annot(area, text=mascara, fontname="Helvetica", fontsize=tam, fill=(1, 1, 1))
                            annot.update()

                # 5. RG e Data de Expedição
                if self.opcoes.get("rg"):
                    for match in self.REGEX_RG_CONTEXTO.finditer(texto_pagina):
                        rg_num = match.group(1).strip()
                        if rg_num:
                            for area in page.search_for(rg_num):
                                tam = max(round(area.height * 0.75, 1), 6)
                                annot = page.add_redact_annot(area, text="RG: XXXXXX", fontname="Helvetica", fontsize=tam, fill=(1, 1, 1))
                                annot.update()

                    for match in self.REGEX_DATA_EXP.finditer(texto_pagina):
                        for area in page.search_for(match.group(0)):
                            tam = max(round(area.height * 0.75, 1), 6)
                            annot = page.add_redact_annot(area, text="Data de Expedição: XX/XX/XXXX", fontname="Helvetica", fontsize=tam, fill=(1, 1, 1))
                            annot.update()

                # 6. Documento SEI e CRC
                if self.opcoes.get("doc_sei"):
                    limite_y_corte = altura_pagina * 0.85
                    areas_assinatura = page.search_for("Documento assinado eletronicamente por")
                    if areas_assinatura:
                        limite_y_corte = min([r.y0 for r in areas_assinatura])

                    for match in self.REGEX_7_DIGITOS.finditer(texto_pagina):
                        numero = match.group()
                        for area in page.search_for(numero):
                            if area.y0 > limite_y_corte:
                                tam = max(round(area.height * 0.75, 1), 6)
                                annot = page.add_redact_annot(area, text=self.mascarar_doc_7_digitos_fmt(numero), fontname="Helvetica", fontsize=tam, align=1, fill=(1, 1, 1))
                                annot.update()

                    areas_auth = page.search_for("A autenticidade do documento pode ser conferida no site")
                    if areas_auth:
                        y_auth = min([r.y0 for r in areas_auth])
                        for match_crc in self.REGEX_CRC.finditer(texto_pagina):
                            crc = match_crc.group()
                            for area in page.search_for(crc):
                                if area.y0 >= y_auth:
                                    tam = max(round(area.height * 0.75, 1), 6)
                                    annot = page.add_redact_annot(area, text="XXXXXXXX", fontname="Helvetica", fontsize=tam, align=1, fill=(0, 0, 0))
                                    annot.update()

                # 7. Termos Customizados Específicos do Usuário (Motor Resiliente)
                for termo_cust in termos_custom:
                    if not termo_cust or not termo_cust.strip():
                        continue
                    retangulos_cust = buscar_retangulos_resilientes(page, texto_pagina, termo_cust)
                    for r in retangulos_cust:
                        tam = max(round(r.height * 0.75, 1), 6)
                        annot = page.add_redact_annot(r, text="[REMOVIDO]", fontname="Helvetica", fontsize=tam, fill=(1, 1, 1))
                        annot.update()

                # 8. Nomes Próprios Inteligentes (Multi-Camadas com Tolerância a PDFs)
                if self.opcoes.get("nomes"):
                    nomes_na_pagina = self.extrair_nomes_inteligente(texto_pagina)
                    for nome_original in nomes_na_pagina:
                        substituto = self._gerar_iniciais(nome_original) if self.opcoes.get("modo_nomes") == "iniciais" else "[NOME]"
                        retangulos_nome = buscar_retangulos_resilientes(page, texto_pagina, nome_original)
                        for area in retangulos_nome:
                            tam = max(round(area.height * 0.75, 1), 6)
                            annot = page.add_redact_annot(area, text=substituto, fontname="Helvetica", fontsize=tam, fill=(1, 1, 1))
                            annot.update()

                page.apply_redactions()

            doc.save(caminho_saida, garbage=4, deflate=True)
            return caminho_saida

        except Exception as e:
            logger.error(f"Falha de processamento PDF em {caminho_entrada}: {e}", exc_info=True)
            raise
        finally:
            if doc:
                doc.close()


class AppAnonimizer:
    """
    Interface Gráfica Moderna, Persistente e High-DPI para o SEI-Anonimizer.
    Mantém-se ativa após cada processamento, possui botão explícito de saída,
    área para termos específicos linha por linha e execução assíncrona com barra de progresso.
    """

    def __init__(self, root: Any):
        if tk is None:
            raise ImportError(
                "A biblioteca Tkinter não está disponível neste ambiente. "
                "Para uso programático ou em contêineres, utilize DocumentAnonimizer ou AnonimizadorTexto."
            )
        self.root = root
        self.root.title(f"Anonimizador de Documentos para Órgãos Públicos - v{__version__}")
        self.root.geometry("820x760")
        self.root.minsize(720, 640)

        # Variáveis de controle
        self.vars = {
            "cpf": tk.BooleanVar(value=True),
            "rg": tk.BooleanVar(value=True),
            "email_tel": tk.BooleanVar(value=True),
            "doc_sei": tk.BooleanVar(value=True),
            "qr_code": tk.BooleanVar(value=True),
            "links": tk.BooleanVar(value=True),
            "nomes": tk.BooleanVar(value=False),  # Desmarcado por padrão (Lazy Loading)
            "modo_nomes": tk.StringVar(value="iniciais")
        }

        self.is_processando = False
        self._configurar_estilos()
        self._construir_interface()

    def _configurar_estilos(self):
        self.style = ttk.Style()
        try:
            self.style.theme_use('clam')
        except Exception:
            pass

        # Cores institucionais e limpas
        self.cor_banner = "#0f4c81"       # Azul institucional Gov / CNPq
        self.cor_fundo = "#f4f6f9"        # Cinza neutro suave
        self.cor_card = "#ffffff"         # Branco para cartões
        self.cor_borda = "#d1d5db"        # Cinza para divisores
        self.cor_sucesso = "#16a34a"      # Verde
        self.cor_texto = "#1e293b"        # Azul grafite escuro

        self.root.configure(bg=self.cor_fundo)

        self.style.configure(".", font=("Segoe UI", 9), background=self.cor_fundo, foreground=self.cor_texto)
        self.style.configure("Card.TFrame", background=self.cor_card, relief="solid", borderwidth=1)
        self.style.configure("Banner.TFrame", background=self.cor_banner)
        self.style.configure("BannerTitulo.TLabel", font=("Segoe UI", 13, "bold"), foreground="#ffffff", background=self.cor_banner)
        self.style.configure("BannerSub.TLabel", font=("Segoe UI", 9), foreground="#e2e8f0", background=self.cor_banner)
        self.style.configure("SecaoTitulo.TLabel", font=("Segoe UI", 10, "bold"), foreground="#0f4c81", background=self.cor_card)
        self.style.configure("CardTexto.TLabel", background=self.cor_card, foreground=self.cor_texto)
        self.style.configure("Card.TCheckbutton", background=self.cor_card, font=("Segoe UI", 9))
        self.style.configure("Card.TRadiobutton", background=self.cor_card, font=("Segoe UI", 9))

        self.style.configure("AcaoPrincipal.TButton", font=("Segoe UI", 9, "bold"), padding=6)
        self.style.configure("AcaoSair.TButton", font=("Segoe UI", 9), padding=6)

    def _construir_interface(self):
        # 1. Banner Superior Elegante
        banner_frame = ttk.Frame(self.root, style="Banner.TFrame", padding=(15, 12))
        banner_frame.pack(fill=tk.X)

        lbl_titulo = ttk.Label(banner_frame, text="Anonimizador de Documentos para Órgãos Públicos", style="BannerTitulo.TLabel")
        lbl_titulo.pack(anchor="w")
        lbl_sub = ttk.Label(banner_frame, text="Tratamento e redação segura de PDFs, Word (.docx) e Textos (.txt) com foco no SEI", style="BannerSub.TLabel")
        lbl_sub.pack(anchor="w", pady=(2, 0))

        # 2. Container Central com Rolagem
        container = ttk.Frame(self.root, padding=12)
        container.pack(fill=tk.BOTH, expand=True)

        canvas = tk.Canvas(container, bg=self.cor_fundo, highlightthickness=0)
        scrollbar = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        window_id = canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(window_id, width=e.width))
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # CARTÃO 1: Opções de Anonimização Padrão
        card_regras = ttk.Frame(scrollable_frame, style="Card.TFrame", padding=12)
        card_regras.pack(fill=tk.X, pady=(0, 10))

        lbl_sec1 = ttk.Label(card_regras, text="1. Regras Padrão de Anonimização", style="SecaoTitulo.TLabel")
        lbl_sec1.pack(anchor="w", pady=(0, 8))

        grid_frame = ttk.Frame(card_regras, style="Card.TFrame")
        grid_frame.pack(fill=tk.X)

        opcoes_chk = [
            ("Mascarar CPFs (***.123.456-**)", "cpf", 0, 0),
            ("Mascarar RGs e Datas de Expedição", "rg", 1, 0),
            ("Mascarar E-mails e Telefones", "email_tel", 2, 0),
            ("Mascarar Nº Documento/Verificador SEI", "doc_sei", 0, 1),
            ("Mascarar QR Codes e Barras Laterais SEI", "qr_code", 1, 1),
            ("Remover todos os Links Clicáveis (PDF)", "links", 2, 1)
        ]

        for texto, chave, lin, col in opcoes_chk:
            chk = ttk.Checkbutton(grid_frame, text=texto, variable=self.vars[chave], style="Card.TCheckbutton")
            chk.grid(row=lin, column=col, sticky="w", padx=10, pady=3)

        ttk.Separator(card_regras, orient='horizontal').pack(fill='x', pady=8)

        # Subseção Nomes Próprios (Lazy Loaded)
        chk_nomes = ttk.Checkbutton(
            card_regras, 
            text="Mascarar Nomes Próprios (Motor Multi-Camadas e Inteligência NLP)", 
            variable=self.vars["nomes"], 
            command=self._toggle_modo_nomes,
            style="Card.TCheckbutton"
        )
        chk_nomes.pack(anchor="w", padx=10, pady=(2, 4))

        self.frame_modos_nome = ttk.Frame(card_regras, style="Card.TFrame")
        self.frame_modos_nome.pack(anchor="w", padx=30, pady=(0, 4))

        self.rb_iniciais = ttk.Radiobutton(
            self.frame_modos_nome, 
            text="Substituir por Iniciais (ex: Alberto Silva -> A. S.)", 
            variable=self.vars["modo_nomes"], 
            value="iniciais", 
            state="disabled",
            style="Card.TRadiobutton"
        )
        self.rb_iniciais.pack(anchor="w", pady=1)

        self.rb_total = ttk.Radiobutton(
            self.frame_modos_nome, 
            text="Ocultação Total (ex: [NOME])", 
            variable=self.vars["modo_nomes"], 
            value="total", 
            state="disabled",
            style="Card.TRadiobutton"
        )
        self.rb_total.pack(anchor="w", pady=1)

        # CARTÃO 2: Termos Específicos Customizados
        card_termos = ttk.Frame(scrollable_frame, style="Card.TFrame", padding=12)
        card_termos.pack(fill=tk.X, pady=(0, 10))

        header_termos = ttk.Frame(card_termos, style="Card.TFrame")
        header_termos.pack(fill=tk.X, pady=(0, 5))

        lbl_sec2 = ttk.Label(header_termos, text="2. Termos Específicos Adicionais para Remoção (um por linha)", style="SecaoTitulo.TLabel")
        lbl_sec2.pack(side=tk.LEFT)

        btn_limpar = ttk.Button(header_termos, text="Limpar Termos", command=self._limpar_termos)
        btn_limpar.pack(side=tk.RIGHT)

        lbl_dica = ttk.Label(
            card_termos, 
            text="Digite abaixo quaisquer termos, nomes, razões sociais, números de processo ou expressões a serem removidas.\n"
                 "Cada linha será tratada como um termo independente (suporta aspas, vírgulas, pontos e barras livremente).\n"
                 "Mecanismo inteligente tolerante a PDFs mal formatados (letras espaçadas, quebras de linha e hifenização).",
            style="CardTexto.TLabel",
            justify=tk.LEFT
        )
        lbl_dica.pack(anchor="w", pady=(0, 5))

        self.txt_termos = scrolledtext.ScrolledText(
            card_termos, 
            height=5, 
            wrap=tk.WORD, 
            font=("Consolas", 9), 
            relief="solid", 
            borderwidth=1
        )
        self.txt_termos.pack(fill=tk.X)

        # CARTÃO 3: Console de Status e Progresso
        card_status = ttk.Frame(scrollable_frame, style="Card.TFrame", padding=12)
        card_status.pack(fill=tk.BOTH, expand=True, pady=(0, 5))

        lbl_sec3 = ttk.Label(card_status, text="3. Status do Processamento", style="SecaoTitulo.TLabel")
        lbl_sec3.pack(anchor="w", pady=(0, 5))

        self.progresso = ttk.Progressbar(card_status, orient="horizontal", mode="determinate")
        self.progresso.pack(fill=tk.X, pady=(0, 5))

        self.txt_log = scrolledtext.ScrolledText(
            card_status, 
            height=6, 
            wrap=tk.WORD, 
            font=("Consolas", 8), 
            state="disabled",
            bg="#f8fafc",
            relief="solid",
            borderwidth=1
        )
        self.txt_log.pack(fill=tk.BOTH, expand=True)

        # 3. Rodapé com Botões de Ação
        rodape = ttk.Frame(self.root, padding=(15, 10))
        rodape.pack(side=tk.BOTTOM, fill=tk.X)

        self.btn_sair = ttk.Button(rodape, text="Sair do Programa", style="AcaoSair.TButton", command=self._sair)
        self.btn_sair.pack(side=tk.LEFT)

        self.btn_dir = ttk.Button(
            rodape, 
            text="Processar Pasta (Lote)...", 
            style="AcaoPrincipal.TButton", 
            command=lambda: self._iniciar_fluxo("diretorio")
        )
        self.btn_dir.pack(side=tk.RIGHT, padx=5)

        self.btn_arq = ttk.Button(
            rodape, 
            text="Processar Arquivo...", 
            style="AcaoPrincipal.TButton", 
            command=lambda: self._iniciar_fluxo("arquivo")
        )
        self.btn_arq.pack(side=tk.RIGHT, padx=5)

        self._adicionar_log(f"SEI-Anonimizer v{__version__} pronto para uso. O programa permanece ativo após os processamentos.")

    def _toggle_modo_nomes(self):
        if self.vars["nomes"].get():
            self.rb_iniciais.config(state="normal")
            self.rb_total.config(state="normal")
        else:
            self.rb_iniciais.config(state="disabled")
            self.rb_total.config(state="disabled")

    def _limpar_termos(self):
        self.txt_termos.delete("1.0", tk.END)

    def _adicionar_log(self, mensagem: str):
        self.txt_log.config(state="normal")
        self.txt_log.insert(tk.END, f"{mensagem}\n")
        self.txt_log.see(tk.END)
        self.txt_log.config(state="disabled")

    def _obter_termos_customizados(self) -> List[str]:
        conteudo = self.txt_termos.get("1.0", tk.END)
        termos = [linha.strip() for linha in conteudo.splitlines() if linha.strip()]
        return termos

    def _sair(self):
        if self.is_processando:
            if not messagebox.askyesno("Confirmar Saída", "Existe um processamento em andamento. Deseja realmente interromper e sair?"):
                return
        self.root.destroy()

    def _iniciar_fluxo(self, tipo_origem: str):
        if self.is_processando:
            messagebox.showwarning("Aviso", "Já existe um processamento em execução. Aguarde a conclusão.")
            return

        extensoes_suportadas = ('.pdf', '.txt', '.docx')
        arquivos_selecionados = []

        if tipo_origem == "diretorio":
            pasta = filedialog.askdirectory(title="Selecione a Pasta para Anonimização em Lote")
            if not pasta:
                return
            for raiz, _, arqs in os.walk(pasta):
                for arq in arqs:
                    if arq.lower().endswith(extensoes_suportadas) and "_anonimizado" not in arq:
                        arquivos_selecionados.append(os.path.join(raiz, arq))
        else:
            arquivo = filedialog.askopenfilename(
                title="Selecione o Documento para Anonimização",
                filetypes=[
                    ("Documentos Suportados", "*.pdf;*.txt;*.docx"),
                    ("PDF", "*.pdf"),
                    ("Texto Puro", "*.txt"),
                    ("Microsoft Word", "*.docx")
                ]
            )
            if not arquivo:
                return
            arquivos_selecionados.append(arquivo)

        if not arquivos_selecionados:
            messagebox.showinfo("Informação", "Nenhum arquivo compatível (.pdf, .docx, .txt) localizado na seleção.")
            return

        # Prepara opções
        opcoes = {k: v.get() for k, v in self.vars.items()}
        opcoes["termos_customizados"] = self._obter_termos_customizados()

        # Inicia processamento assíncrono em segundo plano
        self.is_processando = True
        self.btn_arq.config(state="disabled")
        self.btn_dir.config(state="disabled")

        thread = threading.Thread(
            target=self._executar_processamento_thread, 
            args=(arquivos_selecionados, opcoes), 
            daemon=True
        )
        thread.start()

    def _executar_processamento_thread(self, arquivos: List[str], opcoes: Dict[str, any]):
        total = len(arquivos)
        sucesso = 0
        falhas = 0

        self.root.after(0, lambda: self.progresso.configure(value=0, maximum=total))
        self.root.after(0, lambda: self._adicionar_log(f"--- Iniciando processamento de {total} arquivo(s) ---"))

        termos_custom = opcoes.get("termos_customizados") or []
        if termos_custom:
            self.root.after(0, lambda: self._adicionar_log(f"Termos específicos ativos: {len(termos_custom)} termo(s)"))

        if opcoes.get("nomes"):
            self.root.after(0, lambda: self._adicionar_log("Opção de nomes ativa: verificando e carregando componentes de linguagem..."))

        try:
            with DocumentAnonimizer(opcoes=opcoes) as anonimizador:
                for idx, caminho in enumerate(arquivos, start=1):
                    nome_arq = os.path.basename(caminho)
                    self.root.after(0, lambda n=nome_arq, i=idx: self._adicionar_log(f"[{i}/{total}] Processando: {n}..."))
                    try:
                        caminho_gerado = anonimizador.processar_arquivo(caminho)
                        sucesso += 1
                        self.root.after(0, lambda n=os.path.basename(caminho_gerado): self._adicionar_log(f"  -> Concluído: {n}"))
                    except Exception as err:
                        falhas += 1
                        self.root.after(0, lambda n=nome_arq, e=err: self._adicionar_log(f"  -> FALHA em {n}: {e}"))

                    self.root.after(0, lambda i=idx: self.progresso.configure(value=i))

        except Exception as e_geral:
            self.root.after(0, lambda e=e_geral: self._adicionar_log(f"Erro crítico no lote: {e}"))

        # Finalização mantendo a janela aberta
        def _concluir():
            self.is_processando = False
            self.btn_arq.config(state="normal")
            self.btn_dir.config(state="normal")
            resumo = f"Processamento concluído: {sucesso} gerado(s) com sucesso, {falhas} falha(s)."
            self._adicionar_log(f"--- {resumo} ---")
            messagebox.showinfo("Processamento Concluído", f"{resumo}\n\nO aplicativo permanece ativo para novas operações.")

        self.root.after(0, _concluir)


def iniciar_interface_grafica():
    """
    Ponto de entrada da Interface Gráfica com suporte a DPI Awareness no Windows.
    """
    if tk is None:
        raise ImportError(
            "A interface gráfica (Tkinter) não está disponível neste ambiente. "
            "Para uso programático ou em contêineres, utilize DocumentAnonimizer ou AnonimizadorTexto."
        )

    # Encerra splash de empacotadores se presente
    try:
        import pyi_splash
        pyi_splash.close()
    except ImportError:
        pass

    # Encerra splash screen do Nuitka (onefile) se presente
    if "NUITKA_ONEFILE_PARENT" in os.environ:
        try:
            import tempfile
            splash_filename = os.path.join(
                tempfile.gettempdir(),
                f"onefile_{int(os.environ['NUITKA_ONEFILE_PARENT'])}_splash_feedback.tmp",
            )
            if os.path.exists(splash_filename):
                os.unlink(splash_filename)
        except Exception:
            pass

    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass

    root = tk.Tk()
    app = AppAnonimizer(root)
    root.mainloop()


if __name__ == "__main__":
    iniciar_interface_grafica()