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
    __version__ = "1.2.0"

# Importa módulos internos especializados
from sei_anonimizer.gazetteer import (
    TERMOS_PROTEGIDOS,
    limpar_prefixos_nome,
    validar_candidato_nome,
    normalizar_texto
)
from sei_anonimizer.pdf_matcher import (
    criar_regex_tolerante,
    buscar_retangulos_resilientes,
    ajustar_retangulo_seguranca
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
            "termos_customizados": [],
            "modo_redacao_pdf": "tarja_preta",
            "sanitizar_metadados": True,
            "redigir_imagens": False,
            "limpar_anotacoes": True
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

    def _adicionar_redacao_pdf(
        self,
        page: Any,
        area: Any,
        texto_substituto: str = "",
        fill_custom: Optional[Tuple[float, float, float]] = None
    ) -> Any:
        """
        Adiciona uma anotação de redação ao PDF em estrita conformidade com o modo configurado:
        - "tarja_preta": fill=(0, 0, 0), text="" (Verdadeiro tarjamento SEI nativo, expurga operadores vetoriais).
        - "tarja_branca": fill=(1, 1, 1), text="" (Tarja invisível/branca sem texto residual).
        - "mascara_texto": fill=(1, 1, 1), text=texto_substituto (Carimbo de texto sobreposto).
        """
        modo = self.opcoes.get("modo_redacao_pdf", "tarja_preta")
        area_ajustada = ajustar_retangulo_seguranca(area, padding=0.5)

        if fill_custom is not None:
            annot = page.add_redact_annot(area_ajustada, text="", fill=fill_custom)
            annot.update()
            return annot

        if modo == "tarja_preta":
            annot = page.add_redact_annot(area_ajustada, text="", fill=(0, 0, 0))
            annot.update()
        elif modo == "tarja_branca":
            annot = page.add_redact_annot(area_ajustada, text="", fill=(1, 1, 1))
            annot.update()
        else:  # "mascara_texto"
            tam = max(round(area.height * 0.75, 1), 6)
            annot = page.add_redact_annot(
                area_ajustada,
                text=texto_substituto,
                fontname="Helvetica",
                fontsize=tam,
                fill=(1, 1, 1)
            )
            annot.update()
        return annot

    def _obter_retangulos(self, page: Any, texto_pagina: str, termo: str) -> List[Any]:
        """
        Localiza os retângulos geométricos de um termo na página com resiliência a
        kerning artificial, quebras de linha e translineação.
        """
        if not termo or not texto_pagina:
            return []
        rects = buscar_retangulos_resilientes(page, texto_pagina, termo)
        if not rects:
            rects = page.search_for(termo)
        return rects

    def _sanitizar_metadados_pdf(self, doc: Any, termos_anonimizados: Set[str]):
        """
        Inspeciona e limpa metadados do documento (/Title, /Author, /Subject, /Keywords, /Creator),
        removendo referências confidenciais ou dados pessoais, e expurga fluxos XMP XML.
        """
        try:
            palavras_sensiveis = set()
            stopwords = {"DE", "DA", "DO", "DAS", "DOS", "E", "EM", "POR", "PARA", "COM", "SEM"}
            for t in termos_anonimizados:
                if not t:
                    continue
                t_limpo = t.strip()
                if len(t_limpo) >= 3:
                    palavras_sensiveis.add(t_limpo.lower())
                for p in t_limpo.split():
                    p_limpa = p.strip(".,;:\"'()[]{}")
                    if len(p_limpa) >= 3 and p_limpa.upper() not in stopwords:
                        palavras_sensiveis.add(p_limpa.lower())

            meta = doc.metadata or {}
            novo_meta = {}
            for chave, valor in meta.items():
                if valor is None:
                    continue
                if chave in ("title", "author", "subject", "keywords", "creator"):
                    texto_val = str(valor)
                    # No autor de documento público anonimizado, limpa sempre
                    if chave == "author":
                        novo_meta[chave] = ""
                        continue

                    texto_sanitizado = self._aplicar_substituicoes_texto(texto_val)

                    for ps in palavras_sensiveis:
                        rgx = re.compile(rf'\b{re.escape(ps)}\b', re.IGNORECASE)
                        texto_sanitizado = rgx.sub("", texto_sanitizado)

                    texto_sanitizado = re.sub(r'[\s,;]+', ' ', texto_sanitizado).strip(" ,;")
                    novo_meta[chave] = texto_sanitizado
                else:
                    novo_meta[chave] = valor

            doc.set_metadata(novo_meta)
            if hasattr(doc, "del_xml_metadata"):
                doc.del_xml_metadata()
        except Exception as e:
            logger.warning(f"Erro ao sanitizar metadados do PDF: {e}")

    def _limpar_anotacoes_pdf(self, page: Any, termos_anonimizados: Set[str], rects_redigidos: List[Any]):
        """
        Inspeciona anotações do PDF (comentários, notas, destaques) e remove as que contenham
        termos confidenciais ou que interceptem as áreas tarjadas.
        """
        try:
            for annot in list(page.annots()):
                if annot.type[0] == 12:  # 12 é PDF_ANNOT_REDACT no PyMuPDF
                    continue

                rect_annot = annot.rect
                info = annot.info or {}
                conteudo = (info.get("content") or "") + " " + (info.get("title") or "") + " " + (info.get("subject") or "")

                remover = False
                for r in rects_redigidos:
                    if rect_annot.intersects(r):
                        remover = True
                        break

                if not remover and conteudo.strip():
                    for termo in termos_anonimizados:
                        if termo and len(termo) >= 3 and termo.lower() in conteudo.lower():
                            remover = True
                            break

                if remover:
                    page.delete_annot(annot)
        except Exception as e:
            logger.warning(f"Erro ao auditar anotações da página: {e}")

    def mapear_todas_tarjas_documento(self, doc: Any) -> Tuple[Dict[int, List[Dict[str, Any]]], Set[str]]:
        """
        Analisa todas as páginas do documento PDF e identifica as tarjas automáticas
        de acordo com as regras ativas (CPF, RG, e-mail, telefone, nomes, doc SEI, QR Code, termos customizados).
        
        Returns:
            Tuple com:
            - mapa_tarjas: Dict[int, List[Dict[str, Any]]] onde cada item é {"rect": pymupdf.Rect, "tipo": str, "rotulo": str, "fill_custom": Optional[tuple]}
            - todos_termos_anonimizados: Set[str] com todos os termos localizados.
        """
        try:
            import pymupdf
        except (ImportError, ModuleNotFoundError):
            raise ImportError(
                "A biblioteca pymupdf não está instalada. "
                "Instale com: uv add \"sei-anonimizer[arquivos]\" ou pip install pymupdf"
            )

        termos_custom = self.opcoes.get("termos_customizados") or []
        todos_termos_anonimizados: Set[str] = set(termos_custom)
        mapa_tarjas: Dict[int, List[Dict[str, Any]]] = {}

        for num_pag, page in enumerate(doc):
            texto_pagina = page.get_text("text")
            altura_pagina = page.rect.height
            largura_pagina = page.rect.width
            tarjas_pagina: List[Dict[str, Any]] = []

            # 1. Tarjas de QR Code e Barra Lateral SEI
            if self.opcoes.get("qr_code"):
                rect_barra = pymupdf.Rect(largura_pagina - 25, 0, largura_pagina, altura_pagina)
                tarjas_pagina.append({
                    "rect": rect_barra,
                    "tipo": "barra_sei",
                    "rotulo": "Barra Lateral SEI",
                    "fill_custom": (0, 0, 0)
                })

                areas_auth = page.search_for("A autenticidade do documento pode ser conferida no site")
                if areas_auth:
                    for area in areas_auth:
                        rect_qr = pymupdf.Rect(area.x0 - 60, area.y0 - 10, area.x0, area.y1 + 40)
                        tarjas_pagina.append({
                            "rect": rect_qr,
                            "tipo": "qr_code",
                            "rotulo": "QR Code SEI",
                            "fill_custom": (1, 1, 1)
                        })

            # 2. E-mails e Telefones
            if self.opcoes.get("email_tel"):
                for match in self.REGEX_EMAIL.finditer(texto_pagina):
                    email_enc = match.group()
                    todos_termos_anonimizados.add(email_enc)
                    for area in self._obter_retangulos(page, texto_pagina, email_enc):
                        tarjas_pagina.append({
                            "rect": area,
                            "tipo": "email",
                            "rotulo": "[E-MAIL]",
                            "fill_custom": None
                        })

                for match in self.REGEX_TELEFONE.finditer(texto_pagina):
                    fone = match.group()
                    if not self._eh_telefone_valido(texto_pagina, match.start(), match.end(), fone):
                        continue
                    todos_termos_anonimizados.add(fone)
                    for area in self._obter_retangulos(page, texto_pagina, fone):
                        tarjas_pagina.append({
                            "rect": area,
                            "tipo": "telefone",
                            "rotulo": "[TEL]",
                            "fill_custom": None
                        })

            # 3. CPF
            if self.opcoes.get("cpf"):
                for match in self.REGEX_CPF.finditer(texto_pagina):
                    cpf = match.group()
                    todos_termos_anonimizados.add(cpf)
                    mascara = self.mascarar_cpf_fmt(cpf)
                    for area in self._obter_retangulos(page, texto_pagina, cpf):
                        tarjas_pagina.append({
                            "rect": area,
                            "tipo": "cpf",
                            "rotulo": mascara,
                            "fill_custom": None
                        })

                for match in self.REGEX_CPF_DESFORMATADO.finditer(texto_pagina):
                    cpf_digitos = match.group(1)
                    todos_termos_anonimizados.add(cpf_digitos)
                    mascara = self.mascarar_cpf_fmt(cpf_digitos)
                    for area in self._obter_retangulos(page, texto_pagina, cpf_digitos):
                        tarjas_pagina.append({
                            "rect": area,
                            "tipo": "cpf",
                            "rotulo": mascara,
                            "fill_custom": None
                        })

            # 4. RG e Data de Expedição
            if self.opcoes.get("rg"):
                for match in self.REGEX_RG_CONTEXTO.finditer(texto_pagina):
                    rg_num = match.group(1).strip()
                    if rg_num:
                        todos_termos_anonimizados.add(rg_num)
                        for area in self._obter_retangulos(page, texto_pagina, rg_num):
                            tarjas_pagina.append({
                                "rect": area,
                                "tipo": "rg",
                                "rotulo": "RG: XXXXXX",
                                "fill_custom": None
                            })

                for match in self.REGEX_DATA_EXP.finditer(texto_pagina):
                    data_exp_texto = match.group(0)
                    todos_termos_anonimizados.add(data_exp_texto)
                    for area in self._obter_retangulos(page, texto_pagina, data_exp_texto):
                        tarjas_pagina.append({
                            "rect": area,
                            "tipo": "data_exp",
                            "rotulo": "Data de Expedição: XX/XX/XXXX",
                            "fill_custom": None
                        })

            # 5. Documento SEI e CRC
            if self.opcoes.get("doc_sei"):
                limite_y_corte = altura_pagina * 0.85
                areas_assinatura = page.search_for("Documento assinado eletronicamente por")
                if areas_assinatura:
                    limite_y_corte = min([r.y0 for r in areas_assinatura])

                for match in self.REGEX_7_DIGITOS.finditer(texto_pagina):
                    numero = match.group()
                    areas = self._obter_retangulos(page, texto_pagina, numero)
                    for area in areas:
                        if area.y0 > limite_y_corte:
                            todos_termos_anonimizados.add(numero)
                            tarjas_pagina.append({
                                "rect": area,
                                "tipo": "doc_sei",
                                "rotulo": self.mascarar_doc_7_digitos_fmt(numero),
                                "fill_custom": None
                            })

                areas_auth = page.search_for("A autenticidade do documento pode ser conferida no site")
                if areas_auth:
                    y_auth = min([r.y0 for r in areas_auth])
                    for match_crc in self.REGEX_CRC.finditer(texto_pagina):
                        crc = match_crc.group()
                        areas = self._obter_retangulos(page, texto_pagina, crc)
                        for area in areas:
                            if area.y0 >= y_auth:
                                todos_termos_anonimizados.add(crc)
                                tarjas_pagina.append({
                                    "rect": area,
                                    "tipo": "crc_sei",
                                    "rotulo": "XXXXXXXX",
                                    "fill_custom": (0, 0, 0)
                                })

            # 6. Termos Customizados Específicos
            for termo_cust in termos_custom:
                if not termo_cust or not termo_cust.strip():
                    continue
                todos_termos_anonimizados.add(termo_cust)
                for r in self._obter_retangulos(page, texto_pagina, termo_cust):
                    tarjas_pagina.append({
                        "rect": r,
                        "tipo": "custom",
                        "rotulo": "[REMOVIDO]",
                        "fill_custom": None
                    })

            # 7. Nomes Próprios Inteligentes
            if self.opcoes.get("nomes"):
                nomes_na_pagina = self.extrair_nomes_inteligente(texto_pagina)
                for nome_original in nomes_na_pagina:
                    todos_termos_anonimizados.add(nome_original)
                    substituto = self._gerar_iniciais(nome_original) if self.opcoes.get("modo_nomes") == "iniciais" else "[NOME]"
                    for area in self._obter_retangulos(page, texto_pagina, nome_original):
                        tarjas_pagina.append({
                            "rect": area,
                            "tipo": "nome",
                            "rotulo": substituto,
                            "fill_custom": None
                        })

            mapa_tarjas[num_pag] = tarjas_pagina

        return mapa_tarjas, todos_termos_anonimizados

    def aplicar_tarjas_documento(
        self,
        doc: Any,
        mapa_tarjas: Dict[int, List[Dict[str, Any]]],
        termos_anonimizados: Set[str],
        caminho_saida: str
    ) -> str:
        """
        Aplica fisicamente as tarjas de todas as páginas, remove links, higieniza anotações,
        sanitiza metadados e grava o arquivo de forma sanitizada irreversível.
        """
        try:
            import pymupdf
        except (ImportError, ModuleNotFoundError):
            raise ImportError(
                "A biblioteca pymupdf não está instalada. "
                "Instale com: uv add \"sei-anonimizer[arquivos]\" ou pip install pymupdf"
            )

        for num_pag, page in enumerate(doc):
            tarjas_da_pagina = mapa_tarjas.get(num_pag, [])
            retangulos_pagina = [t["rect"] for t in tarjas_da_pagina]

            # 1. Remoção de links se ativo
            if self.opcoes.get("links"):
                if hasattr(page, "delete_links"):
                    page.delete_links()
                else:
                    for link in page.get_links():
                        page.delete_link(link)

            # 2. Adiciona as anotações de redação
            for item in tarjas_da_pagina:
                self._adicionar_redacao_pdf(
                    page=page,
                    area=item["rect"],
                    texto_substituto=item.get("rotulo", ""),
                    fill_custom=item.get("fill_custom")
                )

            # 3. Limpeza de anotações flutuantes
            if self.opcoes.get("limpar_anotacoes"):
                self._limpar_anotacoes_pdf(page, termos_anonimizados, retangulos_pagina)

            # 4. Expurgo físico no Content Stream
            modo_imagens = (
                getattr(pymupdf, "PDF_REDACT_IMAGE_PIXELS", 2)
                if (self.opcoes.get("redigir_imagens") or self.opcoes.get("qr_code"))
                else getattr(pymupdf, "PDF_REDACT_IMAGE_NONE", 0)
            )
            page.apply_redactions(
                images=modo_imagens,
                graphics=1,
                text=getattr(pymupdf, "PDF_REDACT_TEXT_REMOVE", 0)
            )

        # 5. Sanitização de metadados e expurgo de XML/XMP
        if self.opcoes.get("sanitizar_metadados"):
            self._sanitizar_metadados_pdf(doc, termos_anonimizados)

        doc.save(caminho_saida, garbage=4, deflate=True)
        return caminho_saida

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

            mapa_tarjas, termos_anon = self.mapear_todas_tarjas_documento(doc)
            return self.aplicar_tarjas_documento(doc, mapa_tarjas, termos_anon, caminho_saida)

        except Exception as e:
            logger.error(f"Falha de processamento PDF em {caminho_entrada}: {e}", exc_info=True)
            raise
        finally:
            if doc:
                doc.close()


_ToplevelBase = tk.Toplevel if tk is not None else object


class JanelaTarjamentoPDF(_ToplevelBase):
    """
    Visualizador e Tarjador Interativo de PDFs para o SEI-Anonimizer.

    Renderiza o documento PDF em alta definição página por página no Canvas,
    destaca as tarjas automáticas detectadas e permite ao operador:
    - Desenhar novas tarjas manuais clicando e arrastando com o mouse;
    - Remover tarjas específicas com o botão direito do mouse;
    - Desfazer a última tarja ou limpar todas as tarjas da página;
    - Navegar entre páginas com indicador de progresso;
    - Aplicar o tarjamento físico definitivo e salvar o documento sanitizado.
    """

    def __init__(
        self,
        parent: Any,
        caminho_pdf: str,
        opcoes: Dict[str, Any],
        callback_conclusao: Optional[Any] = None
    ):
        if tk is None:
            raise ImportError(
                "A biblioteca Tkinter não está disponível neste ambiente. "
                "Para uso programático ou em contêineres, utilize DocumentAnonimizer ou AnonimizadorTexto."
            )
        super().__init__(parent)
        self.parent = parent
        self.caminho_pdf = caminho_pdf
        self.opcoes = opcoes
        self.callback_conclusao = callback_conclusao

        self.anonimizador = DocumentAnonimizer(opcoes=self.opcoes)
        self.doc = None

        try:
            import pymupdf
            self.pymupdf = pymupdf
        except (ImportError, ModuleNotFoundError):
            messagebox.showerror("Erro", "A biblioteca pymupdf é necessária para visualizar e tarjar PDFs.")
            self.destroy()
            return

        try:
            self.doc = self.pymupdf.open(self.caminho_pdf)
            if self.doc.is_encrypted:
                messagebox.showerror("Erro", "O documento PDF selecionado está protegido por senha.")
                self.destroy()
                return
        except Exception as e:
            messagebox.showerror("Erro ao Abrir PDF", f"Não foi possível abrir o arquivo PDF:\n{e}")
            self.destroy()
            return

        self.total_paginas = len(self.doc)
        self.pag_atual = 0
        self.dpi = 120
        self.scale = self.dpi / 72.0
        self.x_offset = 20
        self.y_offset = 20

        # Histórico de tarjas para desfazer
        self.historico_acoes = []

        # Pré-carrega tarjas automáticas
        self.mapa_tarjas, self.termos_anon = self.anonimizador.mapear_todas_tarjas_documento(self.doc)

        # Variáveis de interação de desenho
        self.drag_start_x = None
        self.drag_start_y = None
        self.rect_preview_id = None
        self.img_tk = None

        self._configurar_janela()
        self._construir_interface()
        self._renderizar_pagina_atual()

    def _configurar_janela(self):
        nome_arq = os.path.basename(self.caminho_pdf)
        self.title(f"Visualizador e Tarjador Interativo de PDF - {nome_arq}")
        self.geometry("1100x820")
        self.minsize(800, 600)
        self.configure(bg="#f1f5f9")
        self.protocol("WM_DELETE_WINDOW", self._cancelar)
        self.transient(self.parent)
        self.grab_set()

    def _construir_interface(self):
        # 1. Barra de Topo com Informações do Documento
        topo_frame = tk.Frame(self, bg="#0f4c81", padx=15, pady=8)
        topo_frame.pack(fill=tk.X)

        lbl_titulo = tk.Label(
            topo_frame,
            text=f"Tarjamento de PDF: {os.path.basename(self.caminho_pdf)}",
            font=("Segoe UI", 11, "bold"),
            fg="#ffffff",
            bg="#0f4c81"
        )
        lbl_titulo.pack(side=tk.LEFT)

        modo_nome = self.opcoes.get("modo_redacao_pdf", "tarja_preta")
        lbl_modo = tk.Label(
            topo_frame,
            text=f"Modo: {modo_nome.replace('_', ' ').title()}",
            font=("Segoe UI", 9),
            fg="#cbd5e1",
            bg="#0f4c81"
        )
        lbl_modo.pack(side=tk.RIGHT)

        # 2. Barra de Ferramentas e Navegação
        toolbar = tk.Frame(self, bg="#ffffff", relief="ridge", bd=1, padx=12, pady=6)
        toolbar.pack(fill=tk.X)

        self.btn_ant = ttk.Button(toolbar, text="◀ Anterior", command=self._pagina_anterior)
        self.btn_ant.pack(side=tk.LEFT, padx=(0, 6))

        self.lbl_pag = ttk.Label(
            toolbar,
            text=f"Página {self.pag_atual + 1} de {self.total_paginas}",
            font=("Segoe UI", 9, "bold")
        )
        self.lbl_pag.pack(side=tk.LEFT, padx=6)

        self.btn_prox = ttk.Button(toolbar, text="Próxima ▶", command=self._pagina_proxima)
        self.btn_prox.pack(side=tk.LEFT, padx=(6, 15))

        ttk.Separator(toolbar, orient="vertical").pack(side=tk.LEFT, fill=tk.Y, padx=8)

        btn_desfazer = ttk.Button(toolbar, text="Desfazer Última Tarja", command=self._desfazer_ultima)
        btn_desfazer.pack(side=tk.LEFT, padx=4)

        btn_limpar = ttk.Button(toolbar, text="Limpar Tarjas Desta Página", command=self._limpar_pagina)
        btn_limpar.pack(side=tk.LEFT, padx=4)

        self.lbl_contador = ttk.Label(
            toolbar,
            text="",
            font=("Segoe UI", 9)
        )
        self.lbl_contador.pack(side=tk.RIGHT, padx=10)

        # 3. Faixa de Instruções e Dicas
        dica_frame = tk.Frame(self, bg="#f8fafc", padx=12, pady=4, relief="solid", bd=1)
        dica_frame.pack(fill=tk.X)

        lbl_dica = tk.Label(
            dica_frame,
            text="📌 Clique e arraste o mouse para criar novas tarjas manuais (vermelho). "
                 "Tarjas automáticas aparecem em azul. "
                 "Clique com o botão direito sobre uma tarja para excluí-la.",
            font=("Segoe UI", 8),
            fg="#475569",
            bg="#f8fafc"
        )
        lbl_dica.pack(side=tk.LEFT)

        # 4. Área Central do Canvas com Barras de Rolagem
        canvas_container = tk.Frame(self, bg="#334155")
        canvas_container.pack(fill=tk.BOTH, expand=True)

        self.canvas = tk.Canvas(canvas_container, bg="#334155", cursor="cross", highlightthickness=0)
        v_scroll = ttk.Scrollbar(canvas_container, orient=tk.VERTICAL, command=self.canvas.yview)
        h_scroll = ttk.Scrollbar(canvas_container, orient=tk.HORIZONTAL, command=self.canvas.xview)

        self.canvas.configure(xscrollcommand=h_scroll.set, yscrollcommand=v_scroll.set)

        v_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        h_scroll.pack(side=tk.BOTTOM, fill=tk.X)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Button-3>", self._on_right_click)
        self.canvas.bind("<MouseWheel>", self._on_mouse_wheel)

        # 5. Barra Inferior de Ação
        rodape = tk.Frame(self, bg="#ffffff", relief="ridge", bd=1, padx=15, pady=8)
        rodape.pack(side=tk.BOTTOM, fill=tk.X)

        btn_cancelar = ttk.Button(rodape, text="Cancelar", command=self._cancelar)
        btn_cancelar.pack(side=tk.LEFT)

        btn_salvar = ttk.Button(
            rodape,
            text="✔ Aplicar Tarjamento e Salvar PDF...",
            style="AcaoPrincipal.TButton",
            command=self._salvar_e_aplicar
        )
        btn_salvar.pack(side=tk.RIGHT)

    def _renderizar_pagina_atual(self):
        if not self.doc or self.pag_atual >= self.total_paginas:
            return

        self.canvas.delete("all")
        page = self.doc[self.pag_atual]
        pix = page.get_pixmap(dpi=self.dpi)
        self.img_tk = tk.PhotoImage(data=pix.tobytes("png"))

        self.canvas.create_image(self.x_offset, self.y_offset, anchor="nw", image=self.img_tk, tags="page_img")

        total_w = pix.width + (self.x_offset * 2)
        total_h = pix.height + (self.y_offset * 2)
        self.canvas.config(scrollregion=(0, 0, total_w, total_h))

        self.lbl_pag.config(text=f"Página {self.pag_atual + 1} de {self.total_paginas}")
        self.btn_ant.config(state="normal" if self.pag_atual > 0 else "disabled")
        self.btn_prox.config(state="normal" if self.pag_atual < self.total_paginas - 1 else "disabled")

        self._desenhar_tarjas_pagina()

    def _desenhar_tarjas_pagina(self):
        self.canvas.delete("tarja_tag")
        tarjas = self.mapa_tarjas.get(self.pag_atual, [])

        for idx, item in enumerate(tarjas):
            rect = item["rect"]
            sx0 = rect.x0 * self.scale + self.x_offset
            sy0 = rect.y0 * self.scale + self.y_offset
            sx1 = rect.x1 * self.scale + self.x_offset
            sy1 = rect.y1 * self.scale + self.y_offset

            tipo = item.get("tipo", "manual")
            is_manual = (tipo == "manual")
            outline_color = "#ef4444" if is_manual else "#2563eb"

            self.canvas.create_rectangle(
                sx0, sy0, sx1, sy1,
                fill="#000000",
                stipple="gray75",
                outline=outline_color,
                width=2,
                tags=("tarja_tag", f"tarja_{idx}")
            )

            rotulo = "Tarja Manual" if is_manual else item.get("rotulo", "Automática")
            if (sy1 - sy0) >= 10 and (sx1 - sx0) >= 25:
                self.canvas.create_text(
                    sx0 + 4, max(sy0 - 7, self.y_offset),
                    anchor="nw",
                    text=rotulo[:20],
                    font=("Segoe UI", 7, "bold"),
                    fill=outline_color,
                    tags=("tarja_tag", f"tarja_txt_{idx}")
                )

        total_doc = sum(len(t) for t in self.mapa_tarjas.values())
        self.lbl_contador.config(text=f"Tarjas nesta página: {len(tarjas)} | Total no documento: {total_doc}")

    def _pagina_anterior(self):
        if self.pag_atual > 0:
            self.pag_atual -= 1
            self._renderizar_pagina_atual()

    def _pagina_proxima(self):
        if self.pag_atual < self.total_paginas - 1:
            self.pag_atual += 1
            self._renderizar_pagina_atual()

    def _on_mouse_wheel(self, event):
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _on_press(self, event):
        self.drag_start_x = self.canvas.canvasx(event.x)
        self.drag_start_y = self.canvas.canvasy(event.y)
        self.rect_preview_id = self.canvas.create_rectangle(
            self.drag_start_x, self.drag_start_y,
            self.drag_start_x, self.drag_start_y,
            outline="#ef4444",
            width=2,
            dash=(4, 2)
        )

    def _on_drag(self, event):
        if self.rect_preview_id:
            cur_x = self.canvas.canvasx(event.x)
            cur_y = self.canvas.canvasy(event.y)
            self.canvas.coords(self.rect_preview_id, self.drag_start_x, self.drag_start_y, cur_x, cur_y)

    def _on_release(self, event):
        if not self.rect_preview_id:
            return

        end_x = self.canvas.canvasx(event.x)
        end_y = self.canvas.canvasy(event.y)
        self.canvas.delete(self.rect_preview_id)
        self.rect_preview_id = None

        if abs(end_x - self.drag_start_x) < 5 or abs(end_y - self.drag_start_y) < 5:
            return

        page = self.doc[self.pag_atual]
        px0 = (min(self.drag_start_x, end_x) - self.x_offset) / self.scale
        py0 = (min(self.drag_start_y, end_y) - self.y_offset) / self.scale
        px1 = (max(self.drag_start_x, end_x) - self.x_offset) / self.scale
        py1 = (max(self.drag_start_y, end_y) - self.y_offset) / self.scale

        px0 = max(0.0, min(float(page.rect.width), px0))
        py0 = max(0.0, min(float(page.rect.height), py0))
        px1 = max(0.0, min(float(page.rect.width), px1))
        py1 = max(0.0, min(float(page.rect.height), py1))

        if (px1 - px0) >= 3 and (py1 - py0) >= 3:
            novo_rect = self.pymupdf.Rect(px0, py0, px1, py1)
            item = {"rect": novo_rect, "tipo": "manual", "rotulo": "Manual", "fill_custom": None}
            if self.pag_atual not in self.mapa_tarjas:
                self.mapa_tarjas[self.pag_atual] = []
            self.mapa_tarjas[self.pag_atual].append(item)
            self.historico_acoes.append((self.pag_atual, item))
            self._desenhar_tarjas_pagina()

    def _on_right_click(self, event):
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)

        px = (cx - self.x_offset) / self.scale
        py = (cy - self.y_offset) / self.scale

        tarjas = self.mapa_tarjas.get(self.pag_atual, [])
        for i in reversed(range(len(tarjas))):
            rect = tarjas[i]["rect"]
            if rect.contains(self.pymupdf.Point(px, py)):
                tarjas.pop(i)
                self._desenhar_tarjas_pagina()
                break

    def _desfazer_ultima(self):
        if self.historico_acoes:
            pag, item = self.historico_acoes.pop()
            if pag in self.mapa_tarjas and item in self.mapa_tarjas[pag]:
                self.mapa_tarjas[pag].remove(item)
                if self.pag_atual == pag:
                    self._desenhar_tarjas_pagina()
        elif self.mapa_tarjas.get(self.pag_atual):
            self.mapa_tarjas[self.pag_atual].pop()
            self._desenhar_tarjas_pagina()

    def _limpar_pagina(self):
        if self.pag_atual in self.mapa_tarjas:
            self.mapa_tarjas[self.pag_atual].clear()
            self._desenhar_tarjas_pagina()

    def _cancelar(self):
        if self.doc:
            try:
                self.doc.close()
            except Exception:
                pass
        self.destroy()

    def _salvar_e_aplicar(self):
        pasta_origem = os.path.dirname(self.caminho_pdf)
        nome_origem = os.path.basename(self.caminho_pdf)
        sugestao_nome = os.path.splitext(nome_origem)[0] + "_anonimizado.pdf"

        caminho_saida = filedialog.asksaveasfilename(
            parent=self,
            title="Salvar PDF Tarjado Sanitizado",
            initialdir=pasta_origem,
            initialfile=sugestao_nome,
            filetypes=[("Documento PDF", "*.pdf")]
        )
        if not caminho_saida:
            return

        if not caminho_saida.lower().endswith(".pdf"):
            caminho_saida += ".pdf"

        try:
            resultado = self.anonimizador.aplicar_tarjas_documento(
                doc=self.doc,
                mapa_tarjas=self.mapa_tarjas,
                termos_anonimizados=self.termos_anon,
                caminho_saida=caminho_saida
            )
            messagebox.showinfo(
                "Tarjamento Concluído",
                f"O documento foi tarjado e sanitizado com sucesso!\n\nSalvo em:\n{resultado}",
                parent=self
            )
            if self.callback_conclusao:
                self.callback_conclusao(resultado)
            self._cancelar()
        except Exception as e:
            messagebox.showerror("Erro ao Salvar", f"Falha ao aplicar tarjamento no PDF:\n{e}", parent=self)

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
            "modo_nomes": tk.StringVar(value="iniciais"),
            "modo_redacao_pdf": tk.StringVar(value="tarja_preta"),
            "sanitizar_metadados": tk.BooleanVar(value=True),
            "abrir_visualizador": tk.BooleanVar(value=True)
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

        ttk.Separator(card_regras, orient='horizontal').pack(fill='x', pady=8)

        # Subseção Estilo de Tarjamento e Redação em PDFs
        lbl_sub_tarja = ttk.Label(card_regras, text="Estilo de Tarjamento e Redação em PDFs:", style="CardTexto.TLabel", font=("Segoe UI", 9, "bold"))
        lbl_sub_tarja.pack(anchor="w", padx=10, pady=(2, 4))

        frame_tarja = ttk.Frame(card_regras, style="Card.TFrame")
        frame_tarja.pack(anchor="w", padx=20, pady=(0, 4))

        rb_tarja_preta = ttk.Radiobutton(
            frame_tarja,
            text="Tarja Preta Efetiva (Padrão SEI nativo - expurgo físico sem texto residual)",
            variable=self.vars["modo_redacao_pdf"],
            value="tarja_preta",
            style="Card.TRadiobutton"
        )
        rb_tarja_preta.pack(anchor="w", pady=1)

        rb_tarja_branca = ttk.Radiobutton(
            frame_tarja,
            text="Tarja Branca Efetiva (Ocultação limpa/invisível - sem texto residual)",
            variable=self.vars["modo_redacao_pdf"],
            value="tarja_branca",
            style="Card.TRadiobutton"
        )
        rb_tarja_branca.pack(anchor="w", pady=1)

        rb_mascara_texto = ttk.Radiobutton(
            frame_tarja,
            text="Substituição com Texto Mascarado (ex: [E-MAIL], ***.123.456-**, [NOME])",
            variable=self.vars["modo_redacao_pdf"],
            value="mascara_texto",
            style="Card.TRadiobutton"
        )
        rb_mascara_texto.pack(anchor="w", pady=1)

        chk_meta = ttk.Checkbutton(
            card_regras,
            text="Sanitizar Metadados e Propriedades do Arquivo (Título, Autor, Tags XMP/XML)",
            variable=self.vars["sanitizar_metadados"],
            style="Card.TCheckbutton"
        )
        chk_meta.pack(anchor="w", padx=10, pady=(6, 2))

        chk_vis = ttk.Checkbutton(
            card_regras,
            text="Abrir Visualizador Interativo para Tarjamento Manual (exclusivo para PDF)",
            variable=self.vars["abrir_visualizador"],
            style="Card.TCheckbutton"
        )
        chk_vis.pack(anchor="w", padx=10, pady=(2, 4))

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

        # Fluxo interativo exclusivo para arquivos PDF individuais
        if tipo_origem != "diretorio" and len(arquivos_selecionados) == 1:
            arq_unico = arquivos_selecionados[0]
            ext = arq_unico.lower().split('.')[-1]
            if ext == "pdf" and self.vars["abrir_visualizador"].get():
                opcoes = {k: v.get() for k, v in self.vars.items()}
                opcoes["termos_customizados"] = self._obter_termos_customizados()

                def _ao_concluir_tarjamento(caminho_gerado):
                    self._adicionar_log(f"Tarjamento interativo concluído com sucesso: {os.path.basename(caminho_gerado)}")

                JanelaTarjamentoPDF(
                    parent=self.root,
                    caminho_pdf=arq_unico,
                    opcoes=opcoes,
                    callback_conclusao=_ao_concluir_tarjamento
                )
                return
            elif ext in ("docx", "txt") and self.vars["abrir_visualizador"].get():
                self._adicionar_log(
                    f"Nota: Arquivo .{ext} processado automaticamente por substituição textual "
                    f"(a seleção gráfica manual é exclusiva para documentos em PDF)."
                )

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

        modo_red = opcoes.get("modo_redacao_pdf", "tarja_preta")
        meta_status = "Ativa" if opcoes.get("sanitizar_metadados") else "Inativa"
        self.root.after(0, lambda: self._adicionar_log(f"Modo de redação PDF: {modo_red} | Sanitização de Metadados: {meta_status}"))

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