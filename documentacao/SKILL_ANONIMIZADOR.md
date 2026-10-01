---
name: sei-anonimizer
description: Anonimiza e mascara dados sensíveis (CPF, RG, e-mails, telefones, números de documentos SEI, QR Codes, links, nomes próprios e termos customizados) tanto em TEXTO PURO (para prompts de LLMs, chat, RAG, embeddings e respostas reversíveis) quanto em DOCUMENTOS físicos (PDF, Word .docx e texto .txt). Use sempre que precisar higienizar dados pessoais para LGPD ou integrar agentes a fluxos de IA seguros.
---

# Skill: SEI-Anonimizer

Esta skill instrui LLMs, agentes autônomos e desenvolvedores sobre como integrar o pacote **`sei-anonimizer`** em pipelines Python, sistemas de Chat/RAG com IA generativa, bancos de vetores, esteiras de ingestão e robôs de automação (e-Fomento, SEI, etc.).

---

## 1. Visão Geral das Duas Interfaces

O pacote disponibiliza duas interfaces complementares:

| Interface | Módulo | Foco | Dependências Externas | Reversibilidade |
| :--- | :--- | :--- | :---: | :---: |
| **`AnonimizadorTexto`** | `sei_anonimizer.texto` | Texto em memória (prompts, RAG, embeddings, chat com LLM) | **Nenhuma (Zero deps)** | **Sim** (`restaurar`) |
| **`DocumentAnonimizer`** | `sei_anonimizer.main` | Arquivos em disco (`.pdf`, `.docx`, `.txt`) | `pymupdf`, `python-docx` | Não (Redação definitiva) |

---

## 2. Instalação e Configuração

### Instalação via `uv` (Recomendado)
```bash
# Apenas para texto (Chat, RAG, LLM - Ultra-leve, zero dependências, perfeito para containers Docker slim):
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

## 3. Padrões de Uso: `AnonimizadorTexto` (Texto / RAG / LLM)

A classe `AnonimizadorTexto` opera sobre strings em memória. Ela substitui dados sensíveis por **marcadores sequenciais indexados por tipo** (`[EMAIL_1]`, `[TELEFONE_1]`, `[CPF_1]`, `[RG_1]`) e permite **restaurar** os dados reais na resposta gerada pela LLM.

### Regras do Modo Texto:
1. **Nomes de pessoas e cargos NÃO são alterados:** Para permitir que a LLM entenda o contexto administrativo e saiba quem são os interlocutores, nomes próprios e institucionais são preservados.
2. **Mesmo dado = Mesmo marcador:** Na mesma instância, o mesmo e-mail, telefone ou CPF recebe sempre o mesmo marcador.
3. **Tolerância total a variações da LLM:** O método `restaurar` reconhece `[EMAIL_1]`, `[email_1]`, `EMAIL_1` (sem colchetes) e `[ EMAIL_1 ]` (com espaços internos).
4. **Idempotência:** O texto pode ser passado mais de uma vez sem duplicar marcadores ou recontar.
5. **Falha Fechada (Fail-Closed):** Se ocorrer qualquer erro, lança exceção em vez de retornar silenciosamente dados desprotegidos.

---

### Padrão 1: Fluxo Completo de Entrada (Ida) e Saída (Volta) para Usuário com Termo SEI
Para usuários autorizados (com Termo assinado), os dados são anonimizados antes do envio à LLM e restaurados na resposta que volta para a tela:

```python
from sei_anonimizer import AnonimizadorTexto

# 1. Cria uma instância por requisição (ou por sessão de chat)
anonimizador = AnonimizadorTexto()

prompt_usuario = (
    "Por favor, responda ao e-mail de joao.silva@cnpq.br informando que o CPF "
    "111.222.333-44 teve o benefício aprovado. Qualquer dúvida, ligar para (61) 98888-7777."
)

# 2. Anonimiza na IDA (antes de chamar a LLM ou gerar embeddings)
prompt_seguro = anonimizador.anonimizar(prompt_usuario)
# prompt_seguro vira:
# "Por favor, responda ao e-mail de [EMAIL_1] informando que o CPF [CPF_1] teve o benefício aprovado. Qualquer dúvida, ligar para [TELEFONE_1]."

# 3. Chama a LLM passando apenas o texto higienizado
# resposta_llm = cliente_llm.gerar(prompt_seguro)
resposta_llm = "Mensagem enviada para [EMAIL_1]. O titular do CPF [CPF_1] pode ligar no [TELEFONE_1]."

# 4. Restaura na VOLTA para exibição na tela do usuário autenticado
resposta_final = anonimizador.restaurar(resposta_llm)
# resposta_final vira:
# "Mensagem enviada para joao.silva@cnpq.br. O titular do CPF 111.222.333-44 pode ligar no (61) 98888-7777."
```

---

### Padrão 2: Fluxo Unidirecional para Usuário Público (Sem Termo Assinado)
Para usuários públicos ou sem permissão para visualizar dados brutos, a resposta da LLM NÃO é restaurada, e qualquer dado sensível novo gerado pela LLM é também anonimizado:

```python
from sei_anonimizer import AnonimizadorTexto

anonimizador = AnonimizadorTexto()

prompt_publico = "Meu e-mail é contato@gmail.com e meu telefone é (11) 97777-6666."
prompt_seguro = anonimizador.anonimizar(prompt_publico)

# Envia prompt_seguro à LLM
# resposta_llm = cliente_llm.gerar(prompt_seguro)
resposta_llm = "Entendido. Registramos seu contato [EMAIL_1]. Informamos também o fone do plantão: 61 91234-5678."

# Para público: NÃO restaura e ainda anonimiza dados que a própria LLM possa ter citado
resposta_higienizada = anonimizador.anonimizar(resposta_llm)
# Marcadores são preservados e dados novos viram [TELEFONE_2]
```

---

### Padrão 3: Sessão Multi-Turno de Chat (Consistência entre Mensagens)
Em conversas com múltiplas mensagens, mantenha a **mesma instância** de `AnonimizadorTexto` no estado da sessão. Dessa forma, se o usuário mencionar `joao@cnpq.br` no Turno 1 e novamente no Turno 4, o marcador será sempre `[EMAIL_1]`:

```python
from sei_anonimizer import AnonimizadorTexto

class SessaoChat:
    def __init__(self):
        # A instância vive durante todo o diálogo do usuário
        self.anonimizador = AnonimizadorTexto()
        self.historico = []

    def enviar_mensagem(self, texto_usuario: str, client_llm) -> str:
        # Anonimiza a mensagem do usuário reaproveitando o mapa acumulado
        texto_anonimizado = self.anonimizador.anonimizar(texto_usuario)
        self.historico.append({"role": "user", "content": texto_anonimizado})

        # Resposta da LLM
        resposta_llm = client_llm.chat(self.historico)
        self.historico.append({"role": "assistant", "content": resposta_llm})

        # Restaura apenas para a visualização
        return self.anonimizador.restaurar(resposta_llm)
```

---

### Padrão 4: Cache Semântico e Vetorização Segura (Embeddings)
Nunca envie perguntas contendo dados pessoais para modelos de embedding nem persista PII em tabelas de cache compartilhado:

```python
from sei_anonimizer import AnonimizadorTexto

anon = AnonimizadorTexto()
pergunta_crua = "Qual o status do processo de carlos@cnpq.br, CPF 123.456.789-00?"

# 1. Anonimiza antes de consultar o cache ou gerar vetor
pergunta_para_embed = anon.anonimizar(pergunta_crua)

# 2. Gera embedding sobre texto desidentificado
# vetor = modelo_embeddings.embed_query(pergunta_para_embed)

# 3. Grava no cache semântico usando a chave anonimizada
# cache_banco.salvar(chave=pergunta_para_embed, ...)
```

---

### Padrão 5: Inspeção, Contagem e Auditoria de Dados Pessoais
Você pode auditar exatamente quais dados foram encontrados:

```python
from sei_anonimizer import AnonimizadorTexto

anon = AnonimizadorTexto()
anon.anonimizar("Contato: suporte@cnpq.br, fone (61) 3211-0000, CPF 000.111.222-33")

if anon.houve_dado_pessoal:
    print("Contagem por categoria:", anon.contagem())
    # Exibe: {'EMAIL': 1, 'TELEFONE': 1, 'CPF': 1}

    print("Mapeamento interno:")
    for marcador, valor in anon.mapa.items():
        print(f"  {marcador} -> {valor}")
```

---

### Padrão 6: Controle Fino de Tipos
Por padrão, são tratados `("email", "telefone", "cpf", "rg")`. Você pode restringir:

```python
from sei_anonimizer import AnonimizadorTexto

# Anonimizar apenas e-mails e CPFs (ignora telefones e RGs)
anon_parcial = AnonimizadorTexto(tipos=("email", "cpf"))
texto_limpo = anon_parcial.anonimizar("Email: a@b.com, fone: (61) 9999-8888")
# Resultado: "Email: [EMAIL_1], fone: (61) 9999-8888"
```

---

## 4. Padrões de Uso: `DocumentAnonimizer` (Arquivos PDF / Word / TXT)

A classe `DocumentAnonimizer` aplica **redação definitiva física** em PDFs (tarjas pretas/brancas e remoção estrutural de links) e substituições permanentes em DOCX e TXT.

### Estrutura de Opções (`opcoes`):
```python
opcoes = {
    "cpf": True,                 # Mascara no formato ***.123.456-**
    "rg": True,                  # Mascara RG e Data de Expedição
    "email_tel": True,           # Substitui por [E-MAIL] e [TEL]
    "doc_sei": True,             # Mascara número SEI (7 dígitos) e código CRC
    "qr_code": True,             # Tarja QR Code e barra lateral do SEI no PDF
    "links": True,               # Remove anotações de hyperlinks clicáveis no PDF
    "nomes": False,              # Nomes próprios (manter False para boot ultrarrápido < 200ms)
    "modo_nomes": "iniciais",    # "iniciais" (A. C. S.) ou "total" ([NOME])
    "termos_customizados": []    # Lista de termos específicos arbitrários
}
```

### Padrão 7: Processar PDF com Termos Customizados e Tolerância a Formatação
O motor tolerante localiza termos mesmo com *kerning* artificial (`A  l  b  e  r  t  o`), quebras de linha (`Alberto\nde Campos`) ou hifenização (`Alber-\nto`):

```python
from sei_anonimizer import DocumentAnonimizer

config = {
    "cpf": True,
    "rg": True,
    "email_tel": True,
    "doc_sei": True,
    "qr_code": True,
    "nomes": False,  # Boot rápido sem dependência de spaCy
    "termos_customizados": [
        "Mariana Souza e Silva",
        "Empresa XPTO Consultoria Ltda.",
        "Processo Administrativo nº 45.123/2026"
    ]
}

with DocumentAnonimizer(opcoes=config) as anonimizador:
    # Se caminho_saida for omitido, gera {nome}_anonimizado.pdf
    arquivo_gerado = anonimizador.processar_arquivo(
        caminho_entrada="documento_original.pdf",
        caminho_saida="documento_redigido.pdf"
    )
    print(f"PDF redigido e salvo em: {arquivo_gerado}")
```

### Padrão 8: Processamento em Lote em Diretórios
```python
import os
from sei_anonimizer import DocumentAnonimizer

pasta_in = "documentos/originais"
pasta_out = "documentos/anonimizados"
os.makedirs(pasta_out, exist_ok=True)

with DocumentAnonimizer() as anon:
    for arquivo in os.listdir(pasta_in):
        if arquivo.lower().endswith(('.pdf', '.docx', '.txt')) and "_anonimizado" not in arquivo:
            caminho_in = os.path.join(pasta_in, arquivo)
            caminho_out = os.path.join(pasta_out, f"anon_{arquivo}")
            try:
                anon.processar_arquivo(caminho_in, caminho_out)
                print(f"[SUCESSO] {arquivo}")
            except Exception as e:
                print(f"[FALHA] {arquivo}: {e}")
```

---

## 5. Falha Fechada e Boas Práticas de Segurança

1. **Nunca capture exceções para devolver texto cru:**
   ```python
   # INCORRETO (Falha Aberta - Vaza PII):
   try:
       return anon.anonimizar(texto)
   except Exception:
       return texto  # PERIGO: violação grave da LGPD!

   # CORRETO (Falha Fechada):
   try:
       return anon.anonimizar(texto)
   except Exception as e:
       logger.critical(f"Falha de anonimização: {e}")
       raise  # Interrompe o fluxo e não expõe dados desprotegidos
   ```
2. **Arquivos com Senha:** PDFs criptografados (`is_encrypted`) lançam `PermissionError`. Trate especificamente se estiver processando lotes heterogêneos.
3. **Concorrência e Threads:** `AnonimizadorTexto` não possui estado global. Crie uma nova instância por thread ou requisição web (ex: no endpoint do FastAPI).
4. **Gerenciador de Contexto:** Ao usar `DocumentAnonimizer`, use sempre `with DocumentAnonimizer(...) as anon:` para liberação adequada dos ponteiros e descritores de arquivos.
