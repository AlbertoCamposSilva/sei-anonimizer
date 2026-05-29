O nome sugerido para o arquivo é `README.md`.

```markdown
# Anonimizer

## Visão Geral
Ferramenta para anonimização de documentos PDF, projetada para processar e redigir informações sensíveis e dados pessoais. O script opera através de uma interface gráfica nativa (Tkinter) para uso em desktop e de uma classe estruturada (`PDFAnonimizer`) para uso programático em scripts de automação.

## Recursos de Anonimização
O sistema identifica e mascara os seguintes elementos no texto e na estrutura do PDF:
- **CPF:** Formato de saída `***.XXX.XXX-**`
- **RG e Data de Expedição**
- **E-mails e Telefones**
- **Documentos SEI:** Oculta números de 7 dígitos e Códigos de Autenticação (CRC)
- **Elementos Visuais SEI:** Aplica tarjas sobre QR Codes e Barras Laterais de Autenticação
- **Links:** Remoção de hiperlinks da estrutura do arquivo
- **Nomes Próprios:** Identificação por Processamento de Linguagem Natural (NLP) via `spaCy` e expressões regulares de resgate.

## Requisitos e Dependências
O projeto requer Python 3.x e as seguintes bibliotecas:
- `PyMuPDF` (`fitz`): Para leitura e manipulação das camadas do PDF.
- `spacy`: Para o motor de NLP.
- Modelo NLP do spaCy: `pt_core_news_lg`.

### Instalação
```bash
pip install PyMuPDF spacy
python -m spacy download pt_core_news_lg

```

## Uso Programático (Classe `PDFAnonimizer`)

A classe `PDFAnonimizer` é a interface principal para integrar a anonimização em fluxos de dados ou automações de LLM. Deve ser utilizada via gerenciador de contexto (`with`) para gerenciar o estado da execução.

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

Demonstração de configuração personalizada para mascarar apenas CPFs e Nomes.

```python
from anonimizer import PDFAnonimizer

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

with PDFAnonimizer(opcoes=config) as anonimizador:
    # Se o caminho de saída for omitido, gera o arquivo com sufixo '_anonimizado.pdf'
    caminho_saida = anonimizador.processar_arquivo("C:/caminho/para/documento.pdf")
    print(f"Documento tratado salvo em: {caminho_saida}")

```

### Exemplo 2: Processamento em Lote (Automação de Diretórios)

Demonstração de varredura em um diretório definindo um caminho de saída customizado.

```python
import os
from anonimizer import PDFAnonimizer

pasta_origem = "dados/originais"
pasta_destino = "dados/anonimizados"

os.makedirs(pasta_destino, exist_ok=True)

# Utiliza as opções padrão
with PDFAnonimizer() as anonimizador:
    for arquivo in os.listdir(pasta_origem):
        if arquivo.lower().endswith(".pdf"):
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
* `processar_arquivo(self, caminho_entrada: str, caminho_saida: str = None) -> str`: Abre o PDF, aplica as marcações de redação nas coordenadas identificadas pelas Regex e pelo modelo de NLP, e grava o arquivo final (aplicando `garbage=4` e `deflate=True` do PyMuPDF). Retorna o caminho do arquivo gerado.
* `extrair_nomes_nlp(self, texto: str) -> Set[str]`: Executa o modelo `pt_core_news_lg` sobre a string fornecida. Filtra entidades `PER` considerando uma lista restritiva interna (`termos_protegidos`). Retorna um conjunto (`set`) de strings com os nomes validados.

## Interface Gráfica

Para a execução visual interativa, execute o arquivo de forma direta:

```bash
python anonimizer.py

```

```

### Considerações para Implementações Futuras e Automação
1. **Gestão de Memória:** O modelo `pt_core_news_lg` possui alto consumo de RAM na sua inicialização. Em fluxos de LLM que instanciam o script iterativamente, mantenha o escopo de importação em nível global (como já implementado) para evitar recarregamento repetido do modelo.
2. **Tratamento de Exceções em Lote:** PDFs oriundos de scanners podem apresentar tabela de referência cruzada (XREF) corrompida. Mantenha os blocos `try...except` nas iterações de pasta para garantir que um arquivo danificado não interrompa a esteira de processos (conforme Exemplo 2).
3. **Expansão de Whitelist:** Se aplicado em novos órgãos públicos, avalie a modificação da variável `termos_protegidos` dentro do método `extrair_nomes_nlp` para incluir siglas departamentais específicas, mitigando a detecção de falsos positivos pelo modelo de reconhecimento de entidades nomeadas (NER).

```