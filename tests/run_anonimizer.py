"""
Script de demonstração e execução em lote do SEI-Anonimizer.
"""

import os
from sei_anonimizer import DocumentAnonimizer, iniciar_interface_grafica


def tarefa_anonimizacao_batch(lista_arquivos: list, diretorio_destino: str):
    # Configuração customizada das regras de anonimização
    opcoes_customizadas = {
        "cpf": True,
        "rg": True,
        "email_tel": False,  # Preserva dados de contato se desejado
        "doc_sei": True,
        "qr_code": True,
        "links": True,
        "nomes": False,  # Boot rápido sem dependência de spaCy
        "modo_nomes": "iniciais",
        "termos_customizados": [
            "Empresa XPTO Consultoria Ltda.",
            "Processo nº 45.123/2026",
            "Termo Confidencial"
        ]
    }

    os.makedirs(diretorio_destino, exist_ok=True)

    # Utilização do protocolo Context Manager
    with DocumentAnonimizer(opcoes=opcoes_customizadas) as anon:
        for arquivo in lista_arquivos:
            nome_arquivo = os.path.basename(arquivo)
            caminho_final = os.path.join(diretorio_destino, f"anon_{nome_arquivo}")

            try:
                resultado = anon.processar_arquivo(
                    caminho_entrada=arquivo, 
                    caminho_saida=caminho_final
                )
                print(f"Sucesso: {resultado}")
            except FileNotFoundError:
                print(f"Erro: O arquivo {arquivo} não foi localizado no sistema.")
            except Exception as e:
                print(f"Erro crítico no processamento do arquivo {arquivo}: {e}")


if __name__ == "__main__":
    # Altere para True para rodar o lote via CLI, ou False para abrir a interface gráfica
    RODAR_EM_LOTE = False

    if RODAR_EM_LOTE:
        arquivos_pendentes = [
            "/caminho/temporario/parecer_01.pdf",
            "/caminho/temporario/nota_tecnica_12.pdf"
        ]
        tarefa_anonimizacao_batch(arquivos_pendentes, "/caminho/producao/documentos_publicos")
    else:
        iniciar_interface_grafica()