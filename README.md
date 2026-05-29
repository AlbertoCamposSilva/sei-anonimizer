# Anonimizador de Documentos

## Visão Geral
Ferramenta para anonimização de documentos (`.pdf`, `.docx`, `.txt`), projetada para processar e redigir informações sensíveis e dados pessoais. A ferramenta trata a anonimização de documentos do Sistema Eletrônico de Informações (SEI) corretamente, identificando e mascarando padrões específicos da plataforma. O script opera através de uma interface gráfica nativa (Tkinter) e de uma classe estruturada (`DocumentAnonimizer`) para uso programático.

## Recursos de Anonimização
O sistema identifica e mascara os seguintes elementos no texto e na estrutura dos arquivos:
- **Documentos SEI:** Oculta números de 7 dígitos e Códigos de Autenticação (CRC). Em arquivos PDF, aplica tarjas sobre QR Codes e Barras Laterais de Autenticação do sistema. 
- **CPF:** Formato de saída `***.XXX.XXX-**`
- **RG e Data de Expedição**
- **E-mails e Telefones**
- **Links:** Remoção de hiperlinks da estrutura do arquivo (PDF) ou substituição no texto (`.docx`, `.txt`).
- **Nomes Próprios:** Identificação por Processamento de Linguagem Natural (NLP) via `spaCy` e expressões regulares de resgate.

## Requisitos e Dependências
O projeto requer Python 3.x e as seguintes bibliotecas:
- `PyMuPDF` (`fitz`): Para leitura e manipulação das camadas do PDF.
- `python-docx`: Para processamento de arquivos Microsoft Word.
- `spacy`: Para o motor de NLP.
- Modelo NLP do spaCy: `pt_core_news_lg`.

### Instalação
```bash
pip install PyMuPDF python-docx spacy
python -m spacy download pt_core_news_lg

```

## Uso Programático (Classe `DocumentAnonimizer`)

A classe `DocumentAnonimizer` é a interface principal para integrar a anonimização em fluxos de dados ou automações. Deve ser utilizada via gerenciador de contexto (`with`) para gerenciar o estado da execução.

### Estrutura de Opções

O comportamento da classe é definido por um dicionário passado no momento da instanciação. O padrão, caso omitido, é:

```python
opcoes_padrao = {
    "cpf": True,
    "rg": True,
    "email_tel": True,
    "doc_sei": True,
    "qr_code": True,
    "links": True,
    "nomes": False,
    "modo_nomes": "iniciais"  # Alternativa: "total" para [NOME]
}

```

### Exemplo 1: Processamento de Arquivo Único

Demonstração de configuração para mascarar apenas CPFs e Nomes em um arquivo de texto.

```python
from anonimizer import DocumentAnonimizer

config = {
    "cpf": True,
    "nomes": True,
    "modo_nomes": "total", # Substitui nomes identificados por [NOME]
    "email_tel": False,
    "rg": False,
    "doc_sei": False,
    "qr_code": False,
    "links": False
}

with DocumentAnonimizer(opcoes=config) as anonimizador:
    # Se o caminho de saída for omitido, gera o arquivo com sufixo '_anonimizado.docx'
    caminho_saida = anonimizador.processar_arquivo("C:/caminho/para/documento.docx")
    print(f"Documento tratado salvo em: {caminho_saida}")

```

### Exemplo 2: Processamento em Lote (Automação de Diretórios)

Demonstração de varredura em um diretório definindo um caminho de saída customizado.

```python
import os
from anonimizer import DocumentAnonimizer

pasta_origem = "dados/originais"
pasta_destino = "dados/anonimizados"
extensoes_suportadas = ('.pdf', '.docx', '.txt')

os.makedirs(pasta_destino, exist_ok=True)

# Utiliza as opções padrão
with DocumentAnonimizer() as anonimizador:
    for arquivo in os.listdir(pasta_origem):
        if arquivo.lower().endswith(extensoes_suportadas):
            caminho_in = os.path.join(pasta_origem, arquivo)
            caminho_out = os.path.join(pasta_destino, f"tratado_{arquivo}")
            
            try:
                anonimizador.processar_arquivo(caminho_in, caminho_out)
                print(f"Sucesso: {arquivo}")
            except Exception as e:
                print(f"Falha ao processar {arquivo}: {e}")

```

## Referência de Métodos

* `__init__(self, opcoes: Dict[str, bool] = None)`: Inicializa a classe. Atribui o dicionário de opções.
* `processar_arquivo(self, caminho_entrada: str, caminho_saida: str = None) -> str`: Roteia a execução com base na extensão do arquivo (`.pdf`, `.docx`, `.txt`). Aplica as marcações de redação nas coordenadas identificadas (PDF) ou substitui as cadeias de caracteres diretamente no texto (DOCX/TXT). Retorna o caminho do arquivo gerado.
* `extrair_nomes_nlp(self, texto: str) -> Set[str]`: Executa o modelo `pt_core_news_lg` sobre a string fornecida. Filtra entidades `PER` considerando uma lista restritiva interna (`termos_protegidos`). Retorna um conjunto (`set`) de strings com os nomes validados.

## Interface Gráfica

Para a execução visual interativa, execute o arquivo de forma direta:

```bash
python anonimizer.py

```

### Considerações para Implementações Futuras e Automação

1. **Gestão de Memória:** O modelo `pt_core_news_lg` consome recursos na inicialização. Em fluxos que instanciam o script iterativamente, mantenha o escopo de importação em nível global para evitar recarregamento repetido do modelo.
2. **Tratamento de Exceções em Lote:** Arquivos corrompidos ou mal formatados podem gerar erros de leitura. Mantenha os blocos `try...except` nas iterações de pasta para garantir que um arquivo danificado não interrompa a esteira de processos (conforme Exemplo 2).
3. **Expansão de Whitelist:** Se aplicado em outros setores, modifique a variável `termos_protegidos` dentro do método `extrair_nomes_nlp` para incluir siglas departamentais específicas, mitigando a detecção de falsos positivos pelo modelo de reconhecimento de entidades nomeadas (NER).

```

```