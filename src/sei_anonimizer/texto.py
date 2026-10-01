"""
Módulo de Anonimização Reversível de Texto para LLMs e RAG.

Projetado especificamente para esteiras de IA generativa, embeddings e chat:
- Anonimiza dados sensíveis (E-mail, Telefone, CPF e RG) substituindo por marcadores sequenciais.
- Permite restauração exata dos dados reais nas respostas geradas pelas LLMs.
- Tolerante a variações comuns geradas por modelos de linguagem ([email_1], EMAIL_1, etc.).
- Idempotente, thread-safe, com falha fechada (fail-closed) e zero dependências externas.
"""

import re
from typing import Dict, List, Tuple, Optional, Set, Any


class AnonimizadorTexto:
    """
    Anonimizador textual reversível com isolamento por instância.

    Substitui dados sensíveis por marcadores sequenciais por tipo:
    - E-mails: [EMAIL_1], [EMAIL_2], ...
    - Telefones: [TELEFONE_1], [TELEFONE_2], ...
    - CPFs: [CPF_1], [CPF_2], ...
    - RGs: [RG_1], [RG_2], ...

    Garante que o mesmo valor receba sempre o mesmo marcador dentro da mesma instância.
    """

    # 1. E-mail: padrão rigoroso sem o caractere '|' indevido
    REGEX_EMAIL = re.compile(
        r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b'
    )

    # 2. CPF Formatado: 000.000.000-00
    REGEX_CPF_FORMATADO = re.compile(
        r'\b\d{3}\.\d{3}\.\d{3}-\d{2}\b'
    )

    # 3. CPF Não-formatado (11 dígitos): exige contexto da palavra CPF
    REGEX_CPF_DESFORMATADO = re.compile(
        r'(?i:\bCPF\b\s*(?:n[º°.]?|:\s*)?)\s*(\b\d{11}\b)'
    )

    # 4. Telefone: suporta +55, DDD com/sem parênteses, 8 ou 9 dígitos
    REGEX_TELEFONE = re.compile(
        r'(?:\+55\s*)?(?:\(?\d{2}\)?\s*)?(?:9\d{4}|\d{4})[-\s]\d{4}\b'
    )

    # 5. RG Contextual: exige menção explícita a RG ou Identidade
    REGEX_RG_CONTEXTUAL = re.compile(
        r'(?i:\b(?:RG|Identidade)\b\s*(?:n[º°.]?|:\s*)?)\s*([0-9A-Za-z.-]+\s?[0-9A-Za-z]*)'
    )

    # Padrão para identificar se um trecho já é um marcador da biblioteca
    REGEX_MARCADOR_EXISTENTE = re.compile(
        r'\[\s*(EMAIL|TELEFONE|CPF|RG)_\d+\s*\]',
        re.IGNORECASE
    )

    def __init__(self, tipos: Tuple[str, ...] = ("email", "telefone", "cpf", "rg")):
        """
        Inicializa o anonimizador com os tipos selecionados.

        Args:
            tipos: Tupla com os tipos a anonimizar ("email", "telefone", "cpf", "rg").
        """
        self.tipos_ativos: Set[str] = {t.lower().strip() for t in tipos}
        
        # Mapeamento do marcador para o valor original: {"[EMAIL_1]": "joao@cnpq.br"}
        self.mapa: Dict[str, str] = {}

        # Mapeamento reverso para deduplicação: {("email", "joao@cnpq.br"): "[EMAIL_1]"}
        self._mapa_reverso: Dict[Tuple[str, str], str] = {}

        # Contadores sequenciais por tipo
        self._contadores: Dict[str, int] = {
            "EMAIL": 0,
            "TELEFONE": 0,
            "CPF": 0,
            "RG": 0
        }

    @property
    def houve_dado_pessoal(self) -> bool:
        """Retorna True se algum dado pessoal foi detectado e anonimizado nesta instância."""
        return len(self.mapa) > 0

    def contagem(self) -> Dict[str, int]:
        """
        Retorna o total de dados pessoais únicos identificados por tipo.
        Ex: {"EMAIL": 1, "CPF": 2}
        """
        resultado: Dict[str, int] = {}
        for marcador in self.mapa.keys():
            tipo = marcador.strip("[]").split("_")[0]
            resultado[tipo] = resultado.get(tipo, 0) + 1
        return resultado

    def _obter_ou_criar_marcador(self, tipo: str, valor_original: str, chave_canonica: str) -> str:
        """
        Recupera o marcador existente para a chave canônica ou gera um novo sequencial.
        """
        chave = (tipo, chave_canonica)
        if chave in self._mapa_reverso:
            return self._mapa_reverso[chave]

        self._contadores[tipo] += 1
        novo_marcador = f"[{tipo}_{self._contadores[tipo]}]"
        self._mapa_reverso[chave] = novo_marcador
        self.mapa[novo_marcador] = valor_original
        return novo_marcador

    def _eh_telefone_valido(self, texto_completo: str, start: int, end: int, fone_str: str) -> bool:
        """
        Filtro negativo contra falsos positivos para números telefônicos:
        - Descarta 0800 e 0300 (números públicos que não são dados pessoais).
        - Descarta números de processo SEI (ex: 23000.012345/2026-11).
        - Descarta intervalos de anos (ex: 2026-2030).
        - Descarta valores monetários (ex: R$ 1.234,56).
        - Descarta menções a Chamadas/Editais (ex: Chamada 10/2026).
        - Descarta datas completas (ex: 01/09/2026 ou 2026-09-30).
        """
        digitos = re.sub(r'\D', '', fone_str)

        # 1. Ignorar números públicos de atendimento (0800 / 0300)
        fone_limpo = fone_str.strip()
        if fone_limpo.startswith(('0800', '0300', '(0800', '(0300', '+55 0800', '+55 (0800')):
            return False
        if digitos.startswith(('0800', '0300', '550800', '550300')):
            return False

        # 2. Contexto anterior: verificar se é precedido por R$, Chamada, Processo, etc.
        trecho_anterior = texto_completo[max(0, start - 25):start]
        if re.search(r'R\$\s*$', trecho_anterior, re.IGNORECASE):
            return False
        if re.search(r'(?:Chamada|Edital|Portaria|Processo|Parecer|Acórdão|Lei|Decreto)\s+(?:n[º°.]?\s*)?$', trecho_anterior, re.IGNORECASE):
            return False

        # 3. Intervalo de anos (ex: 2026-2030 ou 1995-2000)
        if re.match(r'^(?:19|20)\d{2}[-\s](?:19|20)\d{2}$', fone_limpo):
            return False

        # 4. Contexto amplo: datas ou números de processos com barra
        trecho_amplo = texto_completo[max(0, start - 10):min(len(texto_completo), end + 10)]
        if re.search(r'\d{1,4}[/-]\d{1,2}[/-]\d{2,4}', trecho_amplo):
            return False
        if '/' in trecho_amplo:
            # Números de processo como 012345/2026-11
            return False

        # 5. Validação da quantidade de dígitos
        if len(digitos) in (8, 9, 10, 11, 12, 13):
            # Se for 8 dígitos iniciando com 19 ou 20, pode ser ano
            if len(digitos) == 8 and digitos.startswith(('19', '20')):
                return False
            return True

        return False

    def anonimizar(self, texto: str) -> str:
        """
        Anonimiza o texto informado substituindo dados sensíveis pelos marcadores da instância.
        Idempotente: trechos já marcados não são reprocessados nem recontados.
        Falha fechada: em caso de erro, lança exceção em vez de retornar dados vazados.
        """
        if not texto:
            return texto

        try:
            # 1. E-mails
            if "email" in self.tipos_ativos:
                def _sub_email(match):
                    email = match.group(0)
                    # Não altera se estiver dentro de marcador existente
                    if email.startswith("[") and email.endswith("]"):
                        return email
                    chave = email.lower().strip()
                    return self._obter_ou_criar_marcador("EMAIL", email, chave)

                texto = self.REGEX_EMAIL.sub(_sub_email, texto)

            # 2. Telefones
            if "telefone" in self.tipos_ativos:
                def _sub_telefone(match):
                    fone = match.group(0)
                    start = match.start()
                    end = match.end()
                    if not self._eh_telefone_valido(texto, start, end, fone):
                        return fone
                    
                    digitos = re.sub(r'\D', '', fone)
                    # Normaliza +55 para comparação consistente
                    if digitos.startswith("55") and len(digitos) > 10:
                        chave = digitos[2:]
                    else:
                        chave = digitos
                    return self._obter_ou_criar_marcador("TELEFONE", fone, chave)

                texto = self.REGEX_TELEFONE.sub(_sub_telefone, texto)

            # 3. CPF (Formatado e Desformatado com contexto)
            if "cpf" in self.tipos_ativos:
                # Primeiro os formatados
                def _sub_cpf_fmt(match):
                    cpf = match.group(0)
                    digitos = re.sub(r'\D', '', cpf)
                    if len(digitos) == 11:
                        return self._obter_ou_criar_marcador("CPF", cpf, digitos)
                    return cpf

                texto = self.REGEX_CPF_FORMATADO.sub(_sub_cpf_fmt, texto)

                # Em seguida os desformatados precedidos de 'CPF'
                def _sub_cpf_desfmt(match):
                    texto_todo = match.group(0)
                    cpf_digitos = match.group(1)
                    if len(cpf_digitos) == 11:
                        marcador = self._obter_ou_criar_marcador("CPF", cpf_digitos, cpf_digitos)
                        # Substitui apenas os dígitos, preservando o prefixo contextual "CPF: "
                        idx = texto_todo.rfind(cpf_digitos)
                        return texto_todo[:idx] + marcador + texto_todo[idx + len(cpf_digitos):]
                    return texto_todo

                texto = self.REGEX_CPF_DESFORMATADO.sub(_sub_cpf_desfmt, texto)

            # 4. RG Contextual
            if "rg" in self.tipos_ativos:
                def _sub_rg(match):
                    texto_todo = match.group(0)
                    rg_valor = match.group(1).strip()
                    # Ignora se o valor capturado for vazio ou já for um marcador
                    if not rg_valor or self.REGEX_MARCADOR_EXISTENTE.match(rg_valor):
                        return texto_todo

                    # Chave canônica alfanumérica normalizada
                    chave = re.sub(r'[^A-Za-z0-9]', '', rg_valor).upper()
                    if len(chave) >= 4:
                        marcador = self._obter_ou_criar_marcador("RG", rg_valor, chave)
                        idx = texto_todo.rfind(rg_valor)
                        return texto_todo[:idx] + marcador + texto_todo[idx + len(rg_valor):]
                    return texto_todo

                texto = self.REGEX_RG_CONTEXTUAL.sub(_sub_rg, texto)

            return texto

        except Exception as e:
            # Falha fechada: propaga a exceção para não permitir vazamento silencioso
            raise RuntimeError(f"Erro ao anonimizar texto: {e}") from e

    def restaurar(self, texto: str) -> str:
        """
        Restaura os marcadores de volta aos seus valores originais.

        Tolerante a variações típicas produzidas por LLMs:
        - Case insensitive: [EMAIL_1], [email_1], [Email_1]
        - Sem colchetes: EMAIL_1, email_1
        - Espaços internos: [ EMAIL_1 ], [ email_1 ]
        - Marcadores desconhecidos ou residuais são mantidos inalterados.
        """
        if not texto or not self.mapa:
            return texto

        try:
            texto_restaurado = texto

            for marcador, valor_original in self.mapa.items():
                nome_marcador = marcador.strip("[]")  # ex: "EMAIL_1"
                
                # Regex flexível que aceita:
                # 1. Com colchetes e espaços opcionais: r'\[\s*EMAIL_1\s*\]'
                # 2. Sem colchetes com limite de palavra: r'\bEMAIL_1\b'
                padrao_tolerante = re.compile(
                    rf'\[\s*(?i:{re.escape(nome_marcador)})\s*\]|\b(?i:{re.escape(nome_marcador)})\b'
                )
                texto_restaurado = padrao_tolerante.sub(valor_original, texto_restaurado)

            return texto_restaurado

        except Exception as e:
            raise RuntimeError(f"Erro ao restaurar texto: {e}") from e
