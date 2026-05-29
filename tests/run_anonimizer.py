from sei_anonimizer.main import DocumentAnonimizer 

def tarefa_anonimizacao_batch(lista_arquivos: list, diretorio_destino: str):
    # Configuração customizada das regras de anonimização (opcional)
    opcoes_customizadas = {
        "cpf": True,
        "rg": True,
        "email_tel": False,  # Exemplo: preserva dados de contato
        "doc_sei": True,
        "qr_code": True,
        "links": True,
        "nomes": False,
        "modo_nomes": "iniciais"
    }

    # Utilização do protocolo Context Manager com a classe correta do módulo
    with DocumentAnonimizer(opcoes=opcoes_customizadas) as anon:
        for arquivo in lista_arquivos:
            # os.path.basename garante a extração correta do nome no Windows, Linux ou Mac
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

# Execução do exemplo
if __name__ == "__main__":
    # Altere para True para rodar o lote via CLI, ou False para abrir a interface gráfica
    RODAR_EM_LOTE = True

    if RODAR_EM_LOTE:
        arquivos_pendentes = [
            "/caminho/temporario/parecer_01.pdf",
            "/caminho/temporario/nota_tecnica_12.pdf"
        ]
        tarefa_anonimizacao_batch(arquivos_pendentes, "/caminho/producao/documentos_publicos")
    else:
        iniciar_interface_grafica()