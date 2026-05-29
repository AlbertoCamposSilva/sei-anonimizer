import fitz  # PyMuPDF
import re
import os
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import pandas as pd

class PDFAnonimizer:
    def __init__(self, opcoes: dict = None):
        self.opcoes = opcoes or {
            "cpf": True,
            "rg": True,
            "email_tel": True,
            "doc_sei": True,
            "qr_code": True,
            "links": True
        }
        
        self.regex_cpf = re.compile(r'\b\d{3}\.\d{3}\.\d{3}-\d{2}\b')
        self.regex_rg_contexto = re.compile(r'(RG:)\s*([0-9.-]+\s?\d*)', re.IGNORECASE)
        self.regex_data_exp = re.compile(r'(Data de Expedição:)\s*(\d{2}/\d{2}/\d{4})', re.IGNORECASE)
        self.regex_7_digitos = re.compile(r'\b\d{7}\b')
        self.regex_crc = re.compile(r'\b[0-9A-F]{8}\b', re.IGNORECASE)
        self.regex_email = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b')
        self.regex_telefone = re.compile(r'(?:\(?\d{2}\)?\s?)?(?:9\d{4}|\d{4})[-\s]\d{4}')

        self.nomes_set, self.sobrenomes_set, self.stopwords_set = self._carregar_dados_lattes()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        # Ponto de extensão futuro caso a classe precise desalocar
        # recursos de rede ou conexões persistentes (ex: instâncias do Selenium).
        pass

    @staticmethod
    def resource_path(relative_path: str) -> str:
        try:
            base_path = sys._MEIPASS
        except Exception:
            base_path = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(base_path, relative_path)

    def _carregar_dados_lattes(self) -> tuple:
        try:
            df_nomes = pd.read_csv(self.resource_path("dic_nomes.csv"))
            df_sobrenomes = pd.read_csv(self.resource_path("dic_sobrenomes.csv"))
            df_stopwords = pd.read_csv(self.resource_path("dic_stopwords.csv"))

            return (
                set(df_nomes.iloc[:, 0].astype(str).str.upper()),
                set(df_sobrenomes.iloc[:, 0].astype(str).str.upper()),
                set(df_stopwords.iloc[:, 0].astype(str).str.upper())
            )
        except Exception as e:
            # Em cenários programáticos, pode ser preferível levantar exceção 
            # se os dicionários forem de uso estritamente obrigatório.
            return set(), set(), set()

    @staticmethod
    def mascarar_cpf_fmt(cpf_original: str) -> str:
        numeros = re.sub(r'\D', '', cpf_original)
        if len(numeros) == 11:
            return f"***.{numeros[3:6]}.{numeros[6:9]}-**"
        return "***.***.***-**"

    @staticmethod
    def mascarar_doc_7_digitos_fmt(numero: str) -> str:
        if len(numero) == 7:
            return "XXXXX" + numero[-2:]
        return "XXXXXXX"

    def processar_arquivo(self, caminho_entrada: str, caminho_saida: str = None) -> str:
        """
        Processa e anonimiza um único arquivo PDF.
        Levanta exceções nativas em caso de falha de I/O ou processamento.
        """
        if not caminho_saida:
            pasta_pai = os.path.dirname(caminho_entrada)
            nome_arquivo = os.path.basename(caminho_entrada)
            caminho_saida = os.path.join(pasta_pai, os.path.splitext(nome_arquivo)[0] + "_pb.pdf")

        doc = None
        try:
            doc = fitz.open(caminho_entrada)

            for page in doc:
                texto_pagina = page.get_text()
                altura_pagina = page.rect.height
                largura_pagina = page.rect.width

                if self.opcoes.get("links"):
                    if hasattr(page, "delete_links"):
                        page.delete_links()
                    else:
                        for link in page.get_links():
                            page.delete_link(link)

                if self.opcoes.get("qr_code"):
                    rect_barra_lateral = fitz.Rect(largura_pagina - 25, 0, largura_pagina, altura_pagina)
                    annot = page.add_redact_annot(rect_barra_lateral, fill=(0, 0, 0))
                    annot.update()

                    areas_auth = page.search_for("A autenticidade do documento pode ser conferida no site")
                    if areas_auth:
                        for area in areas_auth:
                            rect_qr_left = fitz.Rect(area.x0 - 60, area.y0 - 10, area.x0, area.y1 + 40)
                            annot = page.add_redact_annot(rect_qr_left, fill=(1, 1, 1))
                            annot.update()

                if self.opcoes.get("email_tel"):
                    for match in self.regex_email.finditer(texto_pagina):
                        areas = page.search_for(match.group())
                        for area in areas:
                            annot = page.add_redact_annot(area, text="[E-MAIL]", fontname="Helvetica", fontsize=8, align=0, fill=(1,1,1))
                            annot.update()

                    for match in self.regex_telefone.finditer(texto_pagina):
                        fone = match.group()
                        if re.match(r'^(19|20)\d{2}-\d{4}', fone): continue
                        
                        areas = page.search_for(fone)
                        for area in areas:
                            annot = page.add_redact_annot(area, text="[TEL]", fontname="Helvetica", fontsize=8, align=0, fill=(1,1,1))
                            annot.update()

                if self.opcoes.get("cpf"):
                    for match in self.regex_cpf.finditer(texto_pagina):
                        cpf = match.group()
                        areas = page.search_for(cpf)
                        mascara = self.mascarar_cpf_fmt(cpf)
                        for area in areas:
                            annot = page.add_redact_annot(area, text=mascara, fontname="Helvetica", fontsize=10, align=0, fill=(1,1,1))
                            annot.update()

                if self.opcoes.get("rg"):
                    for match in self.regex_rg_contexto.finditer(texto_pagina):
                        areas = page.search_for(match.group(0))
                        for area in areas:
                            annot = page.add_redact_annot(area, text="RG: XXXXXX", fontname="Helvetica", fontsize=10, align=0, fill=(1,1,1))
                            annot.update()
                    
                    for match in self.regex_data_exp.finditer(texto_pagina):
                        areas = page.search_for(match.group(0))
                        for area in areas:
                            annot = page.add_redact_annot(area, text="Data de Expedição: XX/XX/XXXX", fontname="Helvetica", fontsize=10, align=0, fill=(1,1,1))
                            annot.update()

                if self.opcoes.get("doc_sei"):
                    limite_y_corte = altura_pagina * 0.85
                    areas_assinatura = page.search_for("Documento assinado eletronicamente por")
                    if areas_assinatura:
                        limite_y_corte = min([r.y0 for r in areas_assinatura])

                    for match in self.regex_7_digitos.finditer(texto_pagina):
                        numero = match.group()
                        areas_num = page.search_for(numero)
                        for area in areas_num:
                            if area.y0 > limite_y_corte:
                                mascara_parcial = self.mascarar_doc_7_digitos_fmt(numero)
                                annot = page.add_redact_annot(area, text=mascara_parcial, fontname="Helvetica", fontsize=9, align=1, fill=(1,1,1))
                                annot.update()
                    
                    areas_auth = page.search_for("A autenticidade do documento pode ser conferida no site")
                    if areas_auth:
                        y_auth = min([r.y0 for r in areas_auth])
                        for match_crc in self.regex_crc.finditer(texto_pagina):
                            crc = match_crc.group()
                            areas_crc = page.search_for(crc)
                            for area in areas_crc:
                                if area.y0 >= y_auth:
                                    annot = page.add_redact_annot(area, text="XXXXXXXX", fontname="Helvetica", fontsize=8, align=1, fill=(0,0,0))
                                    annot.update()

                page.apply_redactions()

            doc.save(caminho_saida, garbage=4, deflate=True)
            return caminho_saida

        finally:
            if doc:
                doc.close()

class DialogoOpcoes(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Configurações de Anonimização")
        self.geometry("700x650")
        self.resultado = None

        self.vars = {
            "cpf": tk.BooleanVar(value=True),
            "rg": tk.BooleanVar(value=True),
            "email_tel": tk.BooleanVar(value=True),
            "doc_sei": tk.BooleanVar(value=True),
            "qr_code": tk.BooleanVar(value=True),
            "links": tk.BooleanVar(value=True)
        }

        frame_instrucoes = ttk.LabelFrame(self, text="Instruções e Avisos de Segurança", padding="10")
        frame_instrucoes.pack(fill=tk.X, padx=10, pady=10)

        texto_instrucoes = (
            "Programa desenvolvido por Alberto de Campos e Silva, do SEADM-DCTI\n\n"
            "Observação 1: A execução de qualquer programa não homologado pela TI representa sério risco de segurança. "
            "Ao executar este programa, você assume que está confiando no programa por mim desenvolvido e que não estou usando de má fé ou que tenho más intenções.\n\n"
            "Observação 2: Nunca execute este programa se tiver recebido esse de terceiros e não do próprio servidor Alberto.\n\n"
            "IMPORTANTE! Eu não assumo qualquer risco ou responsabilidade por danos causados por terceiros ou por modificações maliciosas feitas no programa original. "
            "Também não me responsabilizo por danos causados por erros de uso, falhas de segurança do sistema operacional ou do computador, ou qualquer outro tipo de incidente relacionado à execução deste programa. " 
            "SEMPRE BAIXE E EXECUTE PROGRAMAS APENAS DE FONTES CONFIÁVEIS, E MANTENHA SEU SISTEMA E ANTIVÍRUS ATUALIZADOS.\n\n" 
            "O Script pode ser facilmente modificado com más intenções para, por exemplo, roubar ou alterar arquivos sensíveis do seu computador.\n\n"
            "Como usar:\n"
            "1. Selecione abaixo quais opções e elementos deseja mascarar ou remover dos documentos.\n"
            "2. Clique no botão Confirmar.\n"
            "3. O programa perguntará se deseja processar todos os PDFs de uma pasta inteira ou apenas um arquivo único.\n"
            "4. O programa salvará cópias anonimizadas automaticamente (com o final '_pb.pdf') na mesma pasta do arquivo original."
        )
        
        lbl_instrucoes = ttk.Label(frame_instrucoes, text=texto_instrucoes, justify=tk.LEFT, wraplength=650)
        lbl_instrucoes.pack(fill=tk.X)

        lbl = ttk.Label(self, text="Selecione os elementos para anonimizar:", font=("Arial", 10, "bold"))
        lbl.pack(pady=10)

        opcoes_ui = [
            ("Mascarar CPFs (***.123.456-**)", "cpf"),
            ("Mascarar RGs e Datas (RG: XXXXXX)", "rg"),
            ("Mascarar E-mails e Telefones", "email_tel"),
            ("Mascarar Nº Documento/Verificador (XXXXX11)", "doc_sei"),
            ("Mascarar QR Codes e Barras Laterais (SEI)", "qr_code"),
            ("Remover todos os Links Clicáveis", "links")
        ]

        for texto, chave in opcoes_ui:
            chk = ttk.Checkbutton(self, text=texto, variable=self.vars[chave])
            chk.pack(anchor="w", padx=20, pady=2)

        btn_frame = ttk.Frame(self)
        btn_frame.pack(pady=20)
        
        btn_ok = ttk.Button(btn_frame, text="Confirmar", command=self.confirmar)
        btn_ok.pack(side="left", padx=10)
        
        btn_cancel = ttk.Button(btn_frame, text="Cancelar", command=self.cancelar)
        btn_cancel.pack(side="right", padx=10)

    def confirmar(self):
        self.resultado = {k: v.get() for k, v in self.vars.items()}
        self.destroy()

    def cancelar(self):
        self.resultado = None
        self.destroy()

def iniciar_interface_grafica():
    try:
        import pyi_splash
        pyi_splash.close()
    except ImportError:
        pass

    root = tk.Tk()
    root.withdraw()

    dialogo = DialogoOpcoes(root)
    root.wait_window(dialogo)
    
    opcoes_escolhidas = dialogo.resultado
    if not opcoes_escolhidas:
        print("Operação cancelada pelo usuário.")
        return

    resposta = messagebox.askyesno("Seleção de Origem", 
                                   "Deseja processar uma PASTA inteira?\n\n"
                                   "Sim = Pasta (Recursivo)\nNão = Arquivo Único")

    arquivos_para_processar = []
    
    if resposta: 
        pasta_selecionada = filedialog.askdirectory(title="Selecione a Pasta Raiz")
        if not pasta_selecionada: return
        
        for raiz, dirs, arqs in os.walk(pasta_selecionada):
            for arq in arqs:
                if arq.lower().endswith(".pdf") and "_pb" not in arq:
                    arquivos_para_processar.append(os.path.join(raiz, arq))
    else:
        arquivo = filedialog.askopenfilename(title="Selecione o PDF", filetypes=[("PDF", "*.pdf")])
        if not arquivo: return
        arquivos_para_processar.append(arquivo)

    if not arquivos_para_processar:
        messagebox.showinfo("Info", "Nenhum arquivo PDF encontrado.")
        return

    contador = 0
    total = len(arquivos_para_processar)
    print(f"Iniciando processamento de {total} arquivos...\n")
    
    with PDFAnonimizer(opcoes=opcoes_escolhidas) as anonimizador:
        for caminho in arquivos_para_processar:
            try:
                anonimizador.processar_arquivo(caminho)
                contador += 1
            except Exception as e:
                print(f"Falha ao anonimizar {caminho}: {e}")
            
    messagebox.showinfo("Concluído", f"Processamento finalizado!\n{contador} de {total} arquivos gerados com sucesso.")

if __name__ == "__main__":
    iniciar_interface_grafica()