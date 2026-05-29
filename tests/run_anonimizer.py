from anonimizer import PDFAnonimizer

def tarefa_anonimizacao_batch(lista_arquivos: list, diretorio_destino: str):
    # Configuração customizada das regras de anonimização (opcional)
    opcoes_customizadas = {
        "cpf": True,
        "rg": True,
        "email_tel": False,  # Exemplo: preserva dados de contato
        "doc_sei": True,
        "qr_code": True,
        "links": True
    }

    # Utilização do protocolo Context Manager
    with PDFAnonimizer(opcoes=opcoes_customizadas) as anon:
        for arquivo in lista_arquivos:
            nome_arquivo = arquivo.split("/")[-1]
            caminho_final = f"{diretorio_destino}/anon_{nome_arquivo}"
            
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
    arquivos_pendentes = [
        "/caminho/temporario/parecer_01.pdf",
        "/caminho/temporario/nota_tecnica_12.pdf"
    ]
    tarefa_anonimizacao_batch(arquivos_pendentes, "/caminho/producao/documentos_publicos")