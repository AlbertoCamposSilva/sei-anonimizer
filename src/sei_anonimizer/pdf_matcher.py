"""
Módulo de Busca e Casamento Resiliente de Termos em PDFs Mal Formatados.

Fornece mecanismos de tolerância a anomalias de formatação e extração comuns em PDFs:
1. Kerning artificial / espaçamento solto entre letras (ex: 'A  l  b  e  r  t  o').
2. Caracteres invisíveis (zero-width spaces, non-breaking spaces, soft hyphens).
3. Quebras de linha e hifenização de translineação no meio de termos (ex: 'Alber-\\nto de Campos').
4. Suporte a termos com caracteres especiais, aspas, vírgulas e pontuações.
"""

import re
from typing import List, Optional, Any, TYPE_CHECKING

if TYPE_CHECKING:
    import pymupdf


def criar_regex_tolerante(termo: str) -> Optional[re.Pattern]:
    """
    Compila uma expressão regular altamente resiliente para encontrar o termo informado,
    mesmo que o PDF apresente kerning artificial, quebras de linha ou hifenização.
    
    Args:
        termo: A cadeia de caracteres a ser localizada (qualquer termo, nome ou frase).
        
    Returns:
        Um objeto re.Pattern compilado ou None se o termo for vazio.
    """
    if not termo:
        return None
    termo = termo.strip()
    if not termo:
        return None

    palavras = termo.split()
    padroes_palavras = []

    # Separadores tolerados entre letras da mesma palavra:
    # Espaço, non-breaking space (\xa0), zero-width space (\u200b), soft hyphen (\xad), ponto, traço
    sep_letras = r'[\s\u00A0\u200B\u200C\u200D\u00AD._-]*'

    for palavra in palavras:
        letras_escapadas = [re.escape(c) for c in palavra]
        padrao_palavra = sep_letras.join(letras_escapadas)
        padroes_palavras.append(padrao_palavra)

    # Separador entre palavras consecutivas:
    # Permite 1 ou mais espaços, tabs, quebras de linha (\r?\n) ou hifenização de quebra
    sep_palavras = r'(?:[\s\u00A0\u200B\r\n\t]+|(?:-\s*[\r\n]+\s*))'
    padrao_final = sep_palavras.join(padroes_palavras)

    return re.compile(padrao_final, re.IGNORECASE)


def buscar_retangulos_resilientes(page: Any, texto_pagina: str, termo: str) -> List[Any]:
    """
    Localiza todas as ocorrências de um termo na página do PDF, retornando os retângulos
    geométricos exatos (pymupdf.Rect) mesmo sob anomalias severas de formatação.
    
    Args:
        page: A página pymupdf.Page do PyMuPDF.
        texto_pagina: O texto extraído da página (page.get_text("text")).
        termo: O termo a localizar.
        
    Returns:
        Lista de retângulos cobrindo as ocorrências do termo.
    """
    if not termo or not texto_pagina:
        return []

    rects_encontrados: List[Any] = []
    rgx = criar_regex_tolerante(termo)
    if not rgx:
        return []

    for match in rgx.finditer(texto_pagina):
        match_str = match.group(0)
        
        # 1. Tentativa com a grafia literal exata extraída do PDF
        areas = page.search_for(match_str)
        if areas:
            rects_encontrados.extend(areas)
            continue

        # 2. Se a ocorrência contiver quebra de linha que o PyMuPDF search_for não unificou
        if "\n" in match_str or "\r" in match_str:
            sub_areas = []
            for linha in match_str.splitlines():
                linha_limpa = linha.strip()
                if linha_limpa:
                    sub_areas.extend(page.search_for(linha_limpa))
            if sub_areas:
                rects_encontrados.extend(sub_areas)
                continue

        # 3. Fallback de busca palavra a palavra caso as tentativas anteriores não tenham retornado
        palavras_match = match_str.split()
        for p in palavras_match:
            p_limpa = p.strip(".,;:\"'()[]{}")
            if len(p_limpa) >= 2:
                rects_encontrados.extend(page.search_for(p_limpa))

    return rects_encontrados
