"""
Testes Automatizados para o módulo sei_anonimizer.texto (AnonimizadorTexto).

Cobre:
1. Deduplicação e reutilização de marcadores por valor/instância.
2. Restauração exata e tolerância a variações produzidas por LLMs ([email_1], EMAIL_1, espaços).
3. Idempotência e contadores.
4. Isolamento estrito entre instâncias em concorrência multithread.
5. Filtro de falsos positivos (processos SEI, anos, valores R$, chamadas, datas, 0800).
6. CPFs (formatados e desformatados), telefones (+55, DDD, fixo e celular) e RGs.
7. Importação segura em subprocesso isolado sem dependências gráficas ou de PDF.
"""

import sys
import subprocess
import threading
import pytest

from sei_anonimizer.texto import AnonimizadorTexto
from sei_anonimizer import AnonimizadorTexto as AnonimizadorTextoTopLevel


def test_email_deduplicacao_e_restauracao():
    """Garante que o mesmo e-mail repetido recebe o mesmo marcador e e-mails distintos recebem novos marcadores."""
    anon = AnonimizadorTexto()
    texto = "Contatar joao.silva@cnpq.br ou JOAO.SILVA@CNPQ.BR para suporte. C/C maria@cnpq.br. Novamente joao.silva@cnpq.br."
    
    anonimizado = anon.anonimizar(texto)
    assert "[EMAIL_1]" in anonimizado
    assert "[EMAIL_2]" in anonimizado
    assert "[EMAIL_3]" not in anonimizado
    assert "joao.silva@cnpq.br" not in anonimizado
    assert "maria@cnpq.br" not in anonimizado

    # Contagem e propriedades
    assert anon.houve_dado_pessoal is True
    assert anon.contagem() == {"EMAIL": 2}
    assert anon.mapa["[EMAIL_1]"].lower() == "joao.silva@cnpq.br"
    assert anon.mapa["[EMAIL_2]"] == "maria@cnpq.br"

    # Restauração
    restaurado = anon.restaurar(anonimizado)
    assert "joao.silva@cnpq.br" in restaurado
    assert "maria@cnpq.br" in restaurado


def test_restauracao_tolerancia_llm():
    """Valida que restaurar é tolerante a variações comuns geradas por LLMs."""
    anon = AnonimizadorTexto()
    texto_original = "Envie para carlos@empresa.com e ligue para (61) 99888-7777."
    _ = anon.anonimizar(texto_original)

    # Variações produzidas pela LLM na resposta
    respostas_llm = [
        "Conforme solicitado, respondi ao [EMAIL_1] e avisei no [TELEFONE_1].",
        "Conforme solicitado, respondi ao [email_1] e avisei no [telefone_1].",
        "Conforme solicitado, respondi ao [ Email_1 ] e avisei no [ Telefone_1 ].",
        "Conforme solicitado, respondi ao EMAIL_1 e avisei no TELEFONE_1.",
        "Conforme solicitado, respondi ao email_1 e avisei no telefone_1.",
        "Mantive o marcador desconhecido [EMAIL_99] intacto.",
    ]

    for resp in respostas_llm[:5]:
        restaurado = anon.restaurar(resp)
        assert "carlos@empresa.com" in restaurado
        assert "(61) 99888-7777" in restaurado
        assert "EMAIL_1" not in restaurado
        assert "TELEFONE_1" not in restaurado

    # Marcador desconhecido deve permanecer inalterado
    resp_desconhecida = anon.restaurar("Mantive o marcador desconhecido [EMAIL_99] intacto.")
    assert "[EMAIL_99]" in resp_desconhecida


def test_idempotencia_e_reutilizacao():
    """Anonimizar texto já anonimizado não altera os marcadores nem re-incrementa contadores."""
    anon = AnonimizadorTexto()
    texto = "Servidor: marcos@cnpq.br, telefone (61) 3211-1234."
    
    primeira_vez = anon.anonimizar(texto)
    segunda_vez = anon.anonimizar(primeira_vez)
    assert primeira_vez == segunda_vez
    assert anon.contagem() == {"EMAIL": 1, "TELEFONE": 1}

    # Nova chamada na mesma instância com o mesmo e-mail reutiliza [EMAIL_1]
    outro_texto = "Reiterando e-mail para marcos@cnpq.br com urgência."
    outro_anon = anon.anonimizar(outro_texto)
    assert "[EMAIL_1]" in outro_anon
    assert "[EMAIL_2]" not in outro_anon


def test_isolamento_entre_instancias_e_threads():
    """Garante que instâncias distintas não compartilham estado, mesmo em concorrência."""
    resultados = {}

    def tarefa(thread_id: int, email: str):
        anon = AnonimizadorTexto()
        texto = f"Thread {thread_id}: contatar {email}."
        anonimizado = anon.anonimizar(texto)
        restaurado = anon.restaurar(anonimizado)
        resultados[thread_id] = {
            "marcador": anonimizado,
            "restaurado": restaurado,
            "contagem": anon.contagem(),
            "mapa": anon.mapa
        }

    t1 = threading.Thread(target=tarefa, args=(1, "usuario1@cnpq.br"))
    t2 = threading.Thread(target=tarefa, args=(2, "usuario2@cnpq.br"))

    t1.start()
    t2.start()
    t1.join()
    t2.join()

    # Cada instância começou em 1
    assert "[EMAIL_1]" in resultados[1]["marcador"]
    assert "[EMAIL_1]" in resultados[2]["marcador"]
    assert resultados[1]["mapa"]["[EMAIL_1]"] == "usuario1@cnpq.br"
    assert resultados[2]["mapa"]["[EMAIL_1]"] == "usuario2@cnpq.br"
    assert "usuario1@cnpq.br" in resultados[1]["restaurado"]
    assert "usuario2@cnpq.br" in resultados[2]["restaurado"]


def test_falsos_positivos_preservados():
    """Garante que números de processo, anos, valores em R$, chamadas, datas e 0800 NÃO são mascarados como telefone."""
    anon = AnonimizadorTexto()
    texto_seguro = (
        "Processo nº 23000.012345/2026-11 referente ao período 2026-2030. "
        "Valor concedido: R$ 1.234,56 na Chamada 10/2026. "
        "Data de publicação: 01/09/2026 e término em 2026-09-30. "
        "Central de Atendimento ao Cidadão: 0800 722 7222 ou 0800-722-7222."
    )

    anonimizado = anon.anonimizar(texto_seguro)

    # Nenhum marcador de telefone deve ter sido inserido
    assert "[TELEFONE_" not in anonimizado
    assert "23000.012345/2026-11" in anonimizado
    assert "2026-2030" in anonimizado
    assert "R$ 1.234,56" in anonimizado
    assert "Chamada 10/2026" in anonimizado
    assert "01/09/2026" in anonimizado
    assert "2026-09-30" in anonimizado
    assert "0800 722 7222" in anonimizado
    assert anon.houve_dado_pessoal is False


def test_cpf_com_e_sem_pontuacao():
    """Testa CPFs formatados (000.000.000-00) e desformatados precedidos por CPF."""
    anon = AnonimizadorTexto()
    texto = (
        "Beneficiário 1: 111.222.333-44. "
        "Beneficiário 2: portador do CPF 55566677788 solicitou prorrogação. "
        "Número aleatório longo de 11 dígitos avulsos: 98765432100."
    )

    anonimizado = anon.anonimizar(texto)
    assert "[CPF_1]" in anonimizado
    assert "[CPF_2]" in anonimizado
    assert "111.222.333-44" not in anonimizado
    assert "55566677788" not in anonimizado

    # Número longo sem contexto de CPF deve ser preservado intacto
    assert "98765432100" in anonimizado
    assert anon.contagem() == {"CPF": 2}

    restaurado = anon.restaurar(anonimizado)
    assert "111.222.333-44" in restaurado
    assert "55566677788" in restaurado


def test_telefone_variacoes_e_rg():
    """Valida telefones com +55, DDD com/sem parênteses, celular, fixo e RG contextual."""
    anon = AnonimizadorTexto()
    texto = (
        "Contato 1: +55 (61) 98765-4321. "
        "Contato 2: 61 98765-4321. "
        "Contato 3: 3333-4444. "
        "RG do solicitante: RG: 12.345.678-9 SSP/DF."
    )

    anonimizado = anon.anonimizar(texto)
    # Contato 1 e 2 possuem os mesmos dígitos locais (reutilização)
    assert "[TELEFONE_1]" in anonimizado
    assert "[TELEFONE_2]" in anonimizado
    assert "[RG_1]" in anonimizado
    assert "+55 (61) 98765-4321" not in anonimizado
    assert "3333-4444" not in anonimizado
    assert "12.345.678-9" not in anonimizado

    restaurado = anon.restaurar(anonimizado)
    assert "+55 (61) 98765-4321" in restaurado
    assert "3333-4444" in restaurado
    assert "12.345.678-9" in restaurado


def test_tipos_especificos():
    """Se apenas email for solicitado, não mascara CPF ou telefone."""
    anon = AnonimizadorTexto(tipos=("email",))
    texto = "Email teste@cnpq.br, CPF 111.222.333-44, fone (61) 9999-8888."
    anonimizado = anon.anonimizar(texto)

    assert "[EMAIL_1]" in anonimizado
    assert "111.222.333-44" in anonimizado
    assert "(61) 9999-8888" in anonimizado
    assert anon.contagem() == {"EMAIL": 1}


def test_import_em_ambiente_slim_sem_gui_nem_fitz():
    """Garante que importar sei_anonimizer em subprocesso sem tkinter, pymupdf e fitz não levanta erro."""
    codigo_verificacao = (
        "import sys\n"
        "sys.modules['tkinter'] = None\n"
        "sys.modules['pymupdf'] = None\n"
        "sys.modules['fitz'] = None\n"
        "from sei_anonimizer import AnonimizadorTexto, DocumentAnonimizer\n"
        "from sei_anonimizer.texto import AnonimizadorTexto as AT\n"
        "anon = AnonimizadorTexto()\n"
        "res = anon.anonimizar('Teste joao@cnpq.br')\n"
        "assert '[EMAIL_1]' in res\n"
        "print('SUCCESS_SLIM')\n"
    )

    resultado = subprocess.run(
        [sys.executable, "-c", codigo_verificacao],
        capture_output=True,
        text=True,
        check=True
    )
    assert "SUCCESS_SLIM" in resultado.stdout
