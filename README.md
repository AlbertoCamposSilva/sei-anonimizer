# Anonimizador de Documentos e Textos para Órgãos Públicos (SEI-Anonimizer)

## Visão Geral
Biblioteca Python e ferramenta desktop para anonimização e redação segura de dados sensíveis e pessoais, desenvolvida em conformidade com a LGPD e especializada em atos administrativos e no **Sistema Eletrônico de Informações (SEI)**.

O pacote oferece duas soluções integradas:
1. **`AnonimizadorTexto`:** Anonimização reversível de strings em memória para **LLMs, Chat, RAG e Embeddings**, substituindo dados pessoais por marcadores (`[EMAIL_1]`, `[TELEFONE_1]`, `[CPF_1]`, `[RG_1]`) com capacidade de restaurar os dados reais nas respostas de IA. Possui **zero dependências externas**.
2. **`DocumentAnonimizer`:** Redação definitiva física e lógica de documentos (`.pdf`, `.docx`, `.txt`) com remoção de links, tarjamento de QR Codes e barras laterais do SEI, tolerância a anomalias de PDFs (*kerning*, quebras de linha e hifenização) e **interface gráfica nativa persistente (Tkinter)** com suporte a monitores High-DPI no Windows.

---

## 📚 Documentação do Projeto

O projeto conta com documentação detalhada na pasta [`documentacao/`](./documentacao):

- 🤖 **[Instruções para Agentes e LLMs (SKILL_ANONIMIZADOR.md)](./documentacao/SKILL_ANONIMIZADOR.md):** Manual completo para LLMs e agentes inteligentes aprenderem os múltiplos padrões de chamada do pacote (fluxos bidirecionais de RAG, sessões multi-turno, cache semântico e arquivos físicos).
- 🧑‍💻 **[Guia do Desenvolvedor (GUIA_DO_DESENVOLVEDOR.md)](./documentacao/GUIA_DO_DESENVOLVEDOR.md):** Guia técnico com arquitetura, exemplos práticos em Python, processamento em lote e construção de executáveis.

---

## 🚀 Executável Prontamente Disponível (Sem Código)
Para usuários que não desejam utilizar linhas de comando ou códigos Python, o programa possui um **executável com interface gráfica nativa**, intuitivo e fácil de usar.

🔗 **[Clique aqui para baixar o Executável](https://github.com/AlbertoCamposSilva/sei-anonimizer/releases)**

---

## Recursos de Anonimização

- **Anonimização Reversível para LLMs (`AnonimizadorTexto`):**
  - Marcadores sequenciais por tipo (`[EMAIL_n]`, `[TELEFONE_n]`, `[CPF_n]`, `[RG_n]`).
  - Restauração tolerante a formatações geradas por IA (`[email_1]`, `EMAIL_1`, etc.).
  - Preservação de nomes próprios e institucionais no modo texto para manter o contexto conversacional da LLM.
- **Documentos SEI:** Oculta números de 7 dígitos e Códigos de Autenticação (CRC). Em arquivos PDF, aplica tarjas físicas pretas sobre a barra lateral de autenticação e tarjas brancas sobre o QR Code.
- **CPF:** Formato de saída `***.XXX.XXX-**` ou marcadores sequenciais. Suporta CPFs com e sem pontuação.
- **RG e Data de Expedição:** Ocultação contextual.
- **E-mails e Telefones:** Suporte a `+55`, DDD e descarte de números públicos (`0800`/`0300`).
- **Filtro Estrito Contra Falsos Positivos:** Não mascara números de processos SEI (`23000.012345/2026-11`), anos (`2026-2030`), valores monetários (`R$ 1.234,56`), termos de chamada pública (`Chamada 10/2026`) ou datas.
- **Termos Específicos Customizados:** Localiza termos arbitrários mesmo sob distorções de PDFs (*kerning* `A  l  b  e  r  t  o`, quebras de linha `Alberto\nde Campos` ou hifenizações `Alber-\nto`).

---

## Requisitos e Instalação

### Instalação via `uv` (Recomendado)
```bash
# Apenas para texto (Chat, RAG, LLM - Ultra-leve, zero dependências):
uv add sei-anonimizer

# Para processamento de arquivos PDF e Word (.docx):
uv add "sei-anonimizer[arquivos]"

# Para suporte completo (incluindo NLP spaCy para nomes complexos em documentos):
uv add "sei-anonimizer[all]"
```

### Instalação via `pip`
```bash
pip install sei-anonimizer
pip install "sei-anonimizer[arquivos]"
```

---

## Exemplos Rápidos de Uso

### 1. Anonimização Reversível para LLM/RAG (Modo Texto)
```python
from sei_anonimizer import AnonimizadorTexto

anon = AnonimizadorTexto()

# IDA: Anonimiza o prompt antes de enviar à LLM
prompt_usuario = "Favor enviar o parecer para carlos@cnpq.br. O CPF do bolsista é 111.222.333-44."
prompt_seguro = anon.anonimizar(prompt_usuario)
# "Favor enviar o parecer para [EMAIL_1]. O CPF do bolsista é [CPF_1]."

# VOLTA: Restaura os dados reais na resposta para o usuário autorizado
resposta_llm = "Parecer enviado com sucesso para [EMAIL_1] referente ao [CPF_1]."
resposta_final = anon.restaurar(resposta_llm)
# "Parecer enviado com sucesso para carlos@cnpq.br referente ao 111.222.333-44."
```

### 2. Processamento Físico de PDF com Termos Customizados
```python
from sei_anonimizer import DocumentAnonimizer

opcoes = {
    "cpf": True,
    "rg": True,
    "email_tel": True,
    "doc_sei": True,
    "qr_code": True,
    "termos_customizados": ["Mariana Souza", "Empresa XPTO Ltda."]
}

with DocumentAnonimizer(opcoes=opcoes) as anon:
    caminho_saida = anon.processar_arquivo("documento.pdf")
    print(f"Arquivo redigido: {caminho_saida}")
```

---

## Interface Gráfica

Para abrir a interface gráfica interativa nativa:

```bash
uv run sei-anonimizer
# ou
python -m sei_anonimizer.main
```

---

## Licença

Distribuído sob a Licença Apache 2.0. Consulte o arquivo `LICENSE` para mais detalhes.