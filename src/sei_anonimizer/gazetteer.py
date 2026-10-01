"""
Módulo de Dicionários e Heurísticas de Validação de Nomes Próprios.

Fornece:
1. Base curada dos primeiros nomes brasileiros mais frequentes (IBGE / Registros Civis).
2. Conjunto de termos institucionais protegidos (cidades, capitais, estados, órgãos públicos,
   cargos administrativos e tipos de documentos oficiais) para mitigar 100% de falsos positivos.
3. Normalizadores morfológicos e limpadores de qualificadores contextuais.
"""

import unicodedata
import re
from typing import Set

def normalizar_texto(texto: str) -> str:
    """Remove acentos e converte para maiúsculas para comparações insensíveis a acentos e caixa."""
    if not texto:
        return ""
    nfkd = unicodedata.normalize('NFKD', texto)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).upper().strip()


# Conjunto curado dos primeiros nomes próprios brasileiros mais frequentes
# (Base de dados abertos do Censo Demográfico do IBGE e registros civis)
PRIMEIROS_NOMES_BR: Set[str] = {
    # Masculinos mais frequentes
    "JOSE", "JOAO", "ANTONIO", "FRANCISCO", "CARLOS", "PAULO", "PEDRO", "LUCAS", 
    "LUIZ", "MARCOS", "LUIS", "GABRIEL", "RAFAEL", "DANIEL", "MARCELO", "BRUNO", 
    "EDUARDO", "FELIPE", "RAIMUNDO", "RODRIGO", "MANOEL", "MATEUS", "ANDRE", 
    "FERNANDO", "FABIO", "LEONARDO", "GUSTAVO", "GUILHERME", "LEANDRO", "TIAGO", 
    "ANDERSON", "RICARDO", "MARCIO", "JORGE", "SEBASTIAO", "ALEXANDRE", "ROBERTO", 
    "EDSON", "DIEGO", "VITOR", "SAMUEL", "ALBERTO", "CLEITON", "CESAR", "CLAUDE",
    "ALAN", "ALISSON", "ALVARO", "AMERICO", "ANSELMO", "ARLINDO", "ARMANDO", 
    "ARNALDO", "ARTHUR", "ARTUR", "AUGUSTO", "AURELIO", "BENEDITO", "BERNARDO", 
    "BRENO", "CAIO", "CASSIO", "CELSO", "CICERO", "CLAUDIO", "CRISTIANO", "DAGOBERTO",
    "DALTON", "DANILO", "DARCIO", "DARIO", "DAVI", "DAVID", "DECIO", "DEMETRIO",
    "DENILSON", "DENIS", "DJALMA", "DOMINGOS", "DOUGLAS", "EDER", "EDGARD", "EDGAR",
    "EDILSON", "EDMAR", "EDMILSON", "EDMUNDO", "EDVALDO", "ELCIO", "ELDER", "ELIAS",
    "ELISEU", "ELTON", "EMANUEL", "EMERSON", "EMILIO", "ENIO", "ERIC", "ERICK",
    "ERIVALDO", "ERNESTO", "ESTEVAO", "EVALDO", "EVANDRO", "EVERALDO", "EVERTON",
    "EXPEDITO", "EZEQUIEL", "FABIANO", "FABRICIO", "FAUSTO", "FELICIANO", "FLAVIO",
    "FRANCINALDO", "FREDERICO", "GEOVANE", "GERALDO", "GERSON", "GILBERTO", "GILMAR",
    "GILSON", "GIOVANI", "GIVALDO", "GLAUCO", "HEITOR", "HELCIO", "HELIO", "HENRIQUE",
    "HERCULANO", "HERMES", "HILARIO", "HUGO", "HUMBERTO", "IAGO", "IGOR", "ILDEFONSO",
    "INACIO", "ISAC", "ISMAEL", "ISRAEL", "ITALO", "ITAMAR", "IURI", "IVAN", "IVANILDO",
    "JACI", "JADER", "JAILTON", "JAIME", "JAIR", "JAIRO", "JAMIL", "JANDERSON",
    "JEAN", "JEFFERSON", "JERONIMO", "JESUS", "JOAQUIM", "JOCELINO", "JOEL", "JONAS",
    "JONATAS", "JONATHAN", "JORDAN", "JORGE", "JORGIVAL", "JOSEILTON", "JOSENILDO",
    "JOSEVALDO", "JOSIAS", "JOSUÉ", "JOSUE", "JUAREZ", "JULIANO", "JULIO", "JURANDIR",
    "JUVENAL", "KLEBER", "LAERTE", "LAURO", "LEONEL", "LEVI", "LINEU", "LOURIVAL",
    "LUCAS", "LUCIANO", "LUCIO", "LUDOVICO", "MAGNO", "MAICON", "MAIKON", "MARCIEL",
    "MARCONI", "MARCUS", "MARIO", "MAURICIO", "MAURO", "MAX", "MAXIMILIANO", "MESSIAS",
    "MICHEL", "MILTON", "MOACIR", "MOISES", "MURILO", "NATAN", "NATANAEL", "NELSON",
    "NESTOR", "NEWTON", "NICKOLAS", "NICOLAU", "NILSON", "NILTON", "NIVALDO", "NOE",
    "NORBERTO", "OCTAVIO", "ODAIR", "ODIRLEI", "OLAVO", "ORLANDO", "OSCAR", "OSMAR",
    "OSVALDO", "OTAVIO", "OVIDIO", "PABLO", "PASCOAL", "PATRICK", "PERICLES", "PIETRO",
    "PLINIO", "POLICARPO", "RADAMES", "RAFAEL", "RAMIRO", "RAMON", "RAPHAEL", "RAUL",
    "REGIANE", "REGINALDO", "RENAN", "RENATO", "RENE", "REYNALDO", "RILDO", "RIVALDO",
    "ROBERTO", "ROBSON", "RODOLFO", "ROGER", "ROGERIO", "ROMARIO", "ROMERO", "ROMEU",
    "ROMILDO", "ROMULO", "RONALD", "RONALDO", "RONALDAO", "RONALDINHO", "RONI", "RONILDO",
    "ROQUE", "RUBENS", "RUBEM", "RUDOLF", "RUY", "SABINO", "SALOMAO", "SALVADOR",
    "SANDRO", "SAULO", "SERGIO", "SEVERINO", "SIDNEI", "SILAS", "SILVIO", "SIMAO",
    "TADEU", "TALES", "TARCISIO", "TAYLOR", "TELMO", "TEODORO", "THIAGO", "TOMAS",
    "UBIRATAN", "ULISSES", "VALDECIR", "VALDEMAR", "VALDIR", "VALDOMIRO", "VALENTIM",
    "VALERIO", "VALMIR", "VALTER", "VANDERLEI", "VASCO", "VICENTE", "VINICIUS", "VIRGILIO",
    "VIVALDO", "VLADIMIR", "WAGNER", "WALDEMAR", "WALDIR", "WALMIR", "WALTER", "WASHINGTON",
    "WELLINGTON", "WESLEY", "WILLIAM", "WILLIAN", "WILSON", "YURI",

    # Femininos mais frequentes
    "MARIA", "ANA", "FRANCISCA", "ANTONIA", "ADRIANA", "JULIANA", "MARCIA", "FERNANDA", 
    "PATRICIA", "ALINE", "CAMILA", "AMANDA", "BRUNA", "JESSICA", "LETICIA", "JULIA", 
    "LUCIANA", "VANESSA", "MARIANA", "GABRIELA", "VERA", "VITORIA", "LARISSA", "CLAUDIA", 
    "BEATRIZ", "LUANA", "RITA", "SONIA", "RENATA", "ELIANE", "JOSEFA", "SIMONE", 
    "NATALIA", "CRISTIANE", "CARLA", "DEBORA", "ROSANA", "JAQUELINE", "ROSEMEIRE", 
    "DANIELE", "DANIELA", "MONICA", "ANDREIA", "ANDREA", "TATIANE", "TATIANA", "MARLENE", 
    "TEREZINHA", "SILVIA", "FATIMA", "LUCIA", "REGINA", "ELIZABETH", "ELISABETE",
    "ALEXANDRA", "ALICE", "ALMERINDA", "ALZIRA", "AMALIA", "AMELIA", "ANGELA", "ANGELICA",
    "ANITA", "APARECIDA", "ARIANE", "ARLETE", "AUREA", "BARBARA", "BENEDITA", "BERENICE",
    "BERNADETE", "BIANCA", "BRIGIDA", "CACILDA", "CANDIDA", "CARINA", "CARMEM", "CAROLINA",
    "CAROLINE", "CASSIA", "CATARINA", "CECILIA", "CELIA", "CELINA", "CICERA", "CLARA",
    "CLARICE", "CLEIDE", "CLEONICE", "CLEUSA", "CONCEICAO", "CREUSA", "CRISTINA", "DAIANA",
    "DAIANE", "DALVA", "DAMARIS", "DARCILA", "DAYANE", "DEBORA", "DEISE", "DENISE",
    "DIRCE", "DIVA", "DOROTI", "DULCE", "EDITE", "EDNA", "ELAINE", "ELBA", "ELEN",
    "ELENA", "ELENICE", "ELEONORA", "ELIANA", "ELIDA", "ELISA", "ELISANGELA", "ELITA",
    "ELIZETE", "ELOISA", "ELVIRA", "ELZA", "EMANUELA", "EMILIA", "ENI", "ERICA",
    "ERIKA", "ESTELA", "ESTER", "EUNICE", "EVA", "EVANGELINA", "EVELIN", "EVELYN",
    "FABIANA", "FABIOLA", "FATIMA", "FLAVIA", "FRANCIELLE", "FRANCINE", "GEISA", "GENI",
    "GEOVANA", "GERALDA", "GILDA", "GIOVANA", "GISELE", "GISLAINE", "GLAUCIA", "GLORIA",
    "GRACA", "GRACIELE", "GRAZIELA", "HELENA", "HELOISA", "ILDA", "INES", "IOLANDA",
    "IONE", "IRACEMA", "IRANI", "IRENE", "IRIA", "IRIS", "ISABEL", "ISABELA", "ISADORA",
    "ISAURA", "IVANETE", "IVANI", "IVONE", "IVONETE", "IZABEL", "JACIARA", "JACIRA",
    "JANAINA", "JANETE", "JANICE", "JAQUELINE", "JEANE", "JENNIFER", "JOANA", "JORDANA",
    "JOSEFINA", "JOSIANE", "JOYCE", "JUCARA", "JULIETA", "JUREMA", "JUSSARA", "KAMILA",
    "KAREN", "KARINA", "KARLA", "KATIA", "KEILA", "KELLY", "LAIS", "LARA", "LAURA",
    "LAYLA", "LEA", "LEDA", "LEILA", "LENITA", "LEONOR", "LIA", "LIDIA", "LIGIA",
    "LILIAN", "LILIANA", "LINA", "LINDA", "LORENA", "LOURDES", "LUCILENE", "LUCINEIDE",
    "LUDMILA", "LUIZA", "LURDES", "LUZIA", "MADALENA", "MAGALI", "MAGDA", "MAIRA",
    "MANUELA", "MARA", "MARCELA", "MARGARIDA", "MARIA", "MARILIA", "MARILENE", "MARILUCE",
    "MARILZA", "MARINA", "MARISA", "MARISTELA", "MARIZA", "MARLENE", "MARLI", "MARTA",
    "MATILDE", "MAURA", "MAYARA", "MELISSA", "MERCEDES", "MICHELE", "MILENA", "MIRIAM",
    "MIRIAN", "NADIA", "NAIR", "NARA", "NATALIE", "NAYARA", "NEIDE", "NEUSA", "NILCE",
    "NILZA", "NOEMI", "NURIA", "OLGA", "OLIVIA", "PALOMA", "PAMELA", "PAOLA", "POLIANA",
    "PRISCILA", "RAFAELA", "RAIMUNDA", "RAQUEL", "RAYSSA", "REBECA", "ROBERTA", "ROSALIA",
    "ROSANGELA", "ROSEANE", "ROSELI", "ROSEMARIE", "ROSILENE", "ROSIMEIRE", "RUBIA",
    "RUTE", "SABRINA", "SAMANTHA", "SAMARA", "SANDRA", "SARA", "SARAH", "SEBASTIANA",
    "SELMA", "SHIRLEY", "SILVANA", "SIRLEI", "SOLANGE", "SORAIA", "STEFANI", "STELLA",
    "SUELI", "SUELEN", "SUSANA", "SUZANA", "TAINA", "TAIS", "TALITA", "TANIA", "TATIANE",
    "TEREZA", "TEREZINHA", "THAIS", "THALITA", "VALERIA", "VALQUIRIA", "VANDA", "VANIA",
    "VERONICA", "VIVIAN", "VIVIANE", "YASMIN", "YEDA", "ZELIA", "ZILDA", "ZILMA", "ZULEICA"
}


# Conjunto rigoroso de termos protegidos contra mascaramento indevido
# (Cidades, capitais, estados, órgãos públicos, cargos, tipos documentais e calendário)
TERMOS_PROTEGIDOS: Set[str] = {
    # Capitais e Principais Cidades Brasileiras
    "BRASILIA", "SAO PAULO", "RIO DE JANEIRO", "BELO HORIZONTE", "SALVADOR", "FORTALEZA",
    "CURITIBA", "RECIFE", "PORTO ALEGRE", "BELEM", "GOIANIA", "MANAUS", "CAMPINAS",
    "SAO LUIS", "MACEIO", "NATAL", "TERESINA", "JOAO PESSOA", "ARACAJU", "CUIABA",
    "CAMPO GRANDE", "VITORIA", "FLORIANOPOLIS", "PORTO VELHO", "MACAPA", "RIO BRANCO",
    "BOA VISTA", "PALMAS", "SANTOS", "NITEROI", "UBERLANDIA", "RIBEIRAO PRETO", 
    "SAO JOSE DOS CAMPOS", "SOROCABA", "LONDRINA", "JOINVILLE", "JUIZ DE FORA",
    "ANAPOLIS", "FEIRA DE SANTANA", "CAXIAS DO SUL", "PIRACICABA", "MARINGA", "BAURU",

    # Estados Brasileiros (Nomes e Siglas)
    "ACRE", "ALAGOAS", "AMAPA", "AMAZONAS", "BAHIA", "CEARA", "DISTRITO FEDERAL",
    "ESPIRITO SANTO", "GOIAS", "MARANHAO", "MATO GROSSO", "MATO GROSSO DO SUL",
    "MINAS GERAIS", "PARA", "PARAIBA", "PARANA", "PERNAMBUCO", "PIAUI", "RIO DE JANEIRO",
    "RIO GRANDE DO NORTE", "RIO GRANDE DO SUL", "RONDONIA", "RORAIMA", "SANTA CATARINA",
    "SAO PAULO", "SERGIPE", "TOCANTINS", "BRASIL",

    # Órgãos Públicos, Entidades e Instituições de Ensino/Pesquisa
    "CNPQ", "CAPES", "MCTI", "MEC", "MINISTERIO", "SECRETARIA", "DIRETORIA", 
    "COORDENACAO", "COORDENACAO-GERAL", "DIVISAO", "SERVICO", "DEPARTAMENTO",
    "UNIVERSIDADE", "FACULDADE", "INSTITUTO", "FUNDACAO", "GOVERNO", "PRESIDENCIA",
    "CONSELHO", "TRIBUNAL", "ADVOCACIA-GERAL", "CONTROLADORIA-GERAL", "RECEITA FEDERAL",
    "POLICIA FEDERAL", "BANCO CENTRAL", "EMBRAPA", "FIOCRUZ", "IBAMA", "ICMBIO",
    "INEP", "INPE", "INPI", "ANVISA", "ANATEL", "ANEEL", "ANP", "FAPESP", "FAPERJ",
    "FAPEMIG", "FAPEAM", "SEI", "SISTEMA ELETRONICO DE INFORMACOES", "UNB", "USP", 
    "UNICAMP", "UFRJ", "UFMG", "UFRGS", "UFPE", "UFBA", "UFSC", "UFPR", "UFC",

    # Cargos e Funções Administrativas
    "PRESIDENTE", "VICE-PRESIDENTE", "DIRETOR", "DIRETORA", "COORDENADOR", "COORDENADORA",
    "COORDENADOR-GERAL", "COORDENADORA-GERAL", "ANALISTA", "TECNICO", "TECNICA",
    "ASSISTENTE", "CHEFE", "AUDITOR", "AUDITORA", "PROCURADOR", "PROCURADORA",
    "MINISTRO", "MINISTRA", "SECRETARIO", "SECRETARIA", "GERENTE", "SUPERINTENDENTE",
    "FISCAL", "GESTOR", "GESTORA", "RELATOR", "RELATORA", "CONSULTOR", "CONSULTORA",
    "ASSESSOR", "ASSESSORA", "CONSELHEIRO", "CONSELHEIRA", "DELEGADO", "DELEGADA",

    # Tipos de Documentos Oficiais e Termos Administrativos
    "PORTARIA", "RESOLUCAO", "INSTRUCAO NORMATIVA", "NOTA TECNICA", "PARECER",
    "DESPACHO", "MEMORANDO", "OFICIO", "PROCESSO", "EDITAL", "CHAMADA PUBLICA",
    "TERMO DE OUTORGA", "TERMO DE COMPROMISSO", "CONTRATO", "CONVENIO", "ACORDO",
    "ATA", "RELATORIO", "SOLICITACAO", "REQUERIMENTO", "DECRETO", "LEI", "MEDIDA PROVISORIA",

    # Calendário (Meses e Dias)
    "JANEIRO", "FEVEREIRO", "MARCO", "ABRIL", "MAIO", "JUNHO", 
    "JULHO", "AGOSTO", "SETEMBRO", "OUTUBRO", "NOVEMBRO", "DEZEMBRO",
    "SEGUNDA-FEIRA", "TERCA-FEIRA", "QUARTA-FEIRA", "QUINTA-FEIRA", "SEXTA-FEIRA", "SABADO", "DOMINGO"
}

# Prefixos ou qualificadores que devem ser removidos do início de capturas contextuais
PREFIXOS_QUALIFICADORES = {
    "O", "A", "OS", "AS", "AO", "AOS", "À", "ÀS", "DO", "DA", "DOS", "DAS", "DE", "EM",
    "PELO", "PELA", "PELOS", "PELAS", "PARA", "COM", "POR", "PORTO",
    "PROPONENTE", "SERVIDOR", "SERVIDORA", "INTERESSADO", "INTERESSADA",
    "BOLSISTA", "RELATOR", "RELATORA", "COORDENADOR", "COORDENADORA",
    "REQUERENTE", "MEMBRO", "PESQUISADOR", "PESQUISADORA", "ORIENTADOR", "ORIENTADORA",
    "FISCAL", "GESTOR", "GESTORA", "AUTOR", "AUTORA", "USUARIO", "USUARIA"
}


def limpar_prefixos_nome(nome_bruto: str) -> str:
    """
    Remove artigos, preposições ou qualificadores administrativos (ex: 'O proponente', 'Relator:')
    que possam ter sido capturados no início da string de nome por âncoras contextuais.
    """
    if not nome_bruto:
        return ""
    palavras = nome_bruto.strip().split()
    while palavras:
        palavra_limpa = normalizar_texto(palavras[0].strip(":,;.-– "))
        if palavra_limpa in PREFIXOS_QUALIFICADORES or not palavra_limpa:
            palavras.pop(0)
        else:
            break
    return " ".join(palavras).strip(":,;.-– ")


def validar_candidato_nome(candidato: str) -> bool:
    """
    Verifica se uma cadeia de caracteres tem estrutura válida de nome de pessoa
    e garante que não coincida com termos protegidos (cidades, órgãos, etc.).
    """
    if not candidato:
        return False

    candidato_limpo = " ".join(candidato.strip().split())
    partes = candidato_limpo.split()
    
    # Exige no mínimo 2 palavras e mais de 4 caracteres
    if len(partes) < 2 or len(candidato_limpo) <= 4:
        return False

    cand_norm = normalizar_texto(candidato_limpo)

    # 1. Checa correspondência direta na blacklist de proteção
    if cand_norm in TERMOS_PROTEGIDOS:
        return False

    # 2. Checa se o candidato contém palavras exclusivas de órgãos ou atos administrativos
    palavras_institucionais = {
        "MINISTERIO", "SECRETARIA", "DIRETORIA", "COORDENACAO", "DEPARTAMENTO",
        "UNIVERSIDADE", "INSTITUTO", "PORTARIA", "RESOLUCAO", "EDITAL", "PROCESSO",
        "TRIBUNAL", "GOVERNO", "PRESIDENCIA", "CONSELHO"
    }
    partes_norm = set(cand_norm.split())
    if partes_norm.intersection(palavras_institucionais):
        return False

    # 3. Validação do primeiro nome contra a base morfológica brasileira
    primeiro_nome_norm = normalizar_texto(partes[0])
    return primeiro_nome_norm in PRIMEIROS_NOMES_BR
