# Guia do Desenvolvedor: SEI-Anonimizer

Este guia detalha como utilizar programaticamente, customizar e estender o **SEI-Anonimizer** em seus scripts Python e pipelines de automação no setor público.

---

## 1. Visão Geral da Arquitetura

O **SEI-Anonimizer** é construído em torno de uma arquitetura modular orientada a objetos:

- **`AnonimizadorTexto` (`texto.py`):** Motor de anonimização reversível de strings em memória. Desenvolvido para prompts de LLMs, esteiras RAG, chat e embeddings, utilizando marcadores indexados por tipo (`[EMAIL_1]`, `[TELEFONE_1]`, `[CPF_1]`, `[RG_1]`). Possui **zero dependências externas**, isolamento thread-safe e falha fechada (*fail-closed*).
- **`DocumentAnonimizer` (`main.py`):** Classe orquestradora que gerencia as regras de anonimização, roteia o arquivo de acordo com a extensão (`.pdf`, `.docx`, `.txt`) e aplica as redações físicas ou lógicas definitivas.
- **`gazetteer.py`:** Módulo de alta precisão morfológica. Contém a base dos primeiros nomes mais frequentes do Brasil (IBGE) e o filtro negativo de entidades institucionais protegidas (cidades brasileiras, estados, órgãos públicos federais, cargos e tipos de documentos).
- **`pdf_matcher.py`:** Motor de busca e casamento tolerante a anomalias de PDFs (letras espaçadas por *kerning*, quebras de linha e translineações).
- **`AppAnonimizer` (`main.py`):** Interface gráfica nativa moderna (Tkinter/TTK), com suporte a monitores High-DPI no Windows, processamento multithread assíncrono e ciclo de vida contínuo (não fecha após tratar arquivos).

---

## 2. Instalação e Configuração do Ambiente

Recomenda-se gerenciar o ambiente com o **`uv`**:

```bash
# Para uso apenas com Texto / LLMs / RAG (sem dependências pesadas):
uv add sei-anonimizer

# Para processamento de arquivos PDF e Word (.docx):
uv add "sei-anonimizer[arquivos]"

# Para suporte completo (incluindo NLP spaCy para nomes complexos em documentos):
uv add "sei-anonimizer[all]"
```

Alternativamente, via `pip`:
```bash
pip install "sei-anonimizer[arquivos]"
```

### Ativação Opcional de NLP (spaCy)
Caso deseje utilizar o reconhecimento estatístico complementar para nomes próprios de pessoas raros ou estrangeiros em arquivos:
```bash
uv add "sei-anonimizer[nlp]"
uv run python -m spacy download pt_core_news_lg
```
> **Nota de Desempenho:** O sistema utiliza **Lazy Loading**. Se a opção `"nomes"` estiver desmarcada, o spaCy **não é carregado na memória**, garantindo que a aplicação inicie instantaneamente em menos de 200 ms e consuma menos de 30 MB de RAM.

---

## 3. Uso Programático em Scripts Python

### 3.1. Anonimização Reversível de Texto para LLMs e RAG (`AnonimizadorTexto`)
```python
from sei_anonimizer import AnonimizadorTexto

anon = AnonimizadorTexto()

# 1. Anonimiza na IDA para a LLM
prompt_original = "Enviar parecer para ana.lima@cnpq.br referente ao CPF 123.456.789-00 ou ligar no (61) 98765-4321."
prompt_anonimizado = anon.anonimizar(prompt_original)
# "Enviar parecer para [EMAIL_1] referente ao CPF [CPF_1] ou ligar no [TELEFONE_1]."

# 2. A LLM gera a resposta usando os marcadores
resposta_llm = "Parecer enviado para [EMAIL_1]. O titular do [CPF_1] foi notificado."

# 3. Restaura na VOLTA para usuários autorizados
resposta_final = anon.restaurar(resposta_llm)
# "Parecer enviado para ana.lima@cnpq.br. O titular do 123.456.789-00 foi notificado."
```

### 3.2. Processando um PDF com Termos Personalizados (`DocumentAnonimizer`)
```python
from sei_anonimizer import DocumentAnonimizer

# Configurando as opções
opcoes = {
    "cpf": True,
    "rg": True,
    "email_tel": True,
    "doc_sei": True,
    "qr_code": True,
    "links": True,
    "nomes": False,  # Boot rápido sem spaCy
    "termos_customizados": [
        "Mariana Silva Souza",
        "Empresa XPTO Consultoria",
        "Processo nº 12345/2026",
        '"Termo com aspas e vírgulas, suportado"'
    ]
}

# Processando o arquivo
with DocumentAnonimizer(opcoes=opcoes) as anon:
    caminho_gerado = anon.processar_arquivo("parecer_tecnico.pdf")
    print(f"Documento anonimizado gerado em: {caminho_gerado}")
```

### 3.3. Processamento em Lote com Monitoramento
```python
import os
from sei_anonimizer import DocumentAnonimizer

pasta_in = "documentos/originais"
pasta_out = "documentos/tratados"
os.makedirs(pasta_out, exist_ok=True)

config = {
    "cpf": True,
    "nomes": True,
    "modo_nomes": "iniciais",  # Converte "Carlos Eduardo" para "C. E."
    "termos_customizados": ["Brasília", "Termo Sigiloso"]
}

sucesso = 0
falhas = 0

with DocumentAnonimizer(opcoes=config) as anon:
    for arq in os.listdir(pasta_in):
        if arq.lower().endswith(('.pdf', '.docx', '.txt')) and "_anonimizado" not in arq:
            caminho_entrada = os.path.join(pasta_in, arq)
            caminho_saida = os.path.join(pasta_out, f"anon_{arq}")
            try:
                anon.processar_arquivo(caminho_entrada, caminho_saida)
                print(f"[OK] {arq}")
                sucesso += 1
            except Exception as e:
                print(f"[FALHA] {arq}: {e}")
                falhas += 1

print(f"\nResumo: {sucesso} processados com sucesso, {falhas} falhas.")
```

---

## 4. Tolerância a PDFs Mal Formatados

Em muitos órgãos públicos, documentos impressos em PDF ou gerados por sistemas legados sofrem de distorções na camada de texto:

1. **Espaçamento entre Letras (Kerning):** A palavra `Alberto` pode estar gravada como `A  l  b  e  r  t  o`.
2. **Quebra de Linha:** Nomes ou termos compostos podem estar partidos entre duas linhas (`Alberto de\nCampos e Silva`).
3. **Hifenização:** Separação silábica de final de linha (`Alber-\nto Silva`).

O compilador `criar_regex_tolerante` no módulo `pdf_matcher.py` decompõe o termo dinamicamente:
- Entre cada letra, permite separadores invisíveis, espaços nulos e traços.
- Entre cada palavra, permite quebras de linha e hífens opcionais.
- Ao encontrar a ocorrência real na camada de texto da página, recupera os retângulos geométricos exatos (`pymupdf.Rect`) correspondentes via PyMuPDF e aplica tarjas físicas definitivas (`add_redact_annot`).

---

## 5. Proteção Contra Falsos Positivos

Para garantir que o código **não remova nomes de cidades, de órgãos públicos ou de cargos administrativos**:

1. **Padrões Contextuais com Limite de Linha:** Só extrai nomes vinculados a âncoras como *"assinado eletronicamente por"*, *"Interessado(a):"* ou *"portador do CPF"*, com parada estrita na quebra de linha.
2. **Limpador de Qualificadores:** Descarta automaticamente palavras contextuais que acompanham a menção (ex: transforma *"O proponente MARCOS ANTONIO"* em *"MARCOS ANTONIO"*).
3. **Morfologia com Base IBGE:** Exige que o primeiro nome pertença à base dos primeiros nomes mais frequentes do país.
4. **Filtro Negativo Estrito:** Qualquer termo presente na lista de cidades, estados, ministérios, diretorias, portarias ou resoluções é **preservado imediatamente**.
5. **Filtro de Telefones:** Não confunde números de processo SEI (`23000.012345/2026-11`), anos (`2026-2030`), valores em reais (`R$ 1.234,56`), números de chamada (`Chamada 10/2026`), datas (`01/09/2026`) ou canais públicos de atendimento (`0800`).

---

## 6. Construção do Executável (.exe) e Pacotes

Para compilar o executável ou construir os pacotes com o `uv`:

```cmd
build.bat
```

Ou diretamente via linha de comando:
```bash
# Executável independente
uv run pyinstaller --noconfirm --onefile --windowed --splash "src\sei_anonimizer\loading.png" "src\sei_anonimizer\main.py"

# Pacotes Wheel e Tar.gz para PyPI
uv build
```
