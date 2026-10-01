@echo off
REM Construção do executável com PyInstaller via uv
uv run pyinstaller --noconfirm --onefile --windowed --splash "src\sei_anonimizer\loading.png" --paths "src" --collect-all spacy --collect-all pt_core_news_lg "src\sei_anonimizer\main.py"

REM Limpeza de builds anteriores e geração dos novos pacotes (wheel e sdist) via uv
if exist dist\*.whl del /q dist\*.whl
if exist dist\*.tar.gz del /q dist\*.tar.gz
uv build

REM Publicação no PyPI:
REM uv publish