@echo off
REM Preparação de ativos Tcl/Tk para compilação com Nuitka no Python 3.14 (Tcl 9)
if not exist "build_cache" mkdir build_cache
uv run python -c "import zipfile, sys, os, shutil; dlls = os.path.join(sys.base_prefix, 'DLLs'); shutil.copyfile(os.path.join(dlls, 'tcl90.dll'), 'build_cache/tcl.zip') if not os.path.exists('build_cache/tcl.zip') else None; shutil.copyfile(os.path.join(dlls, 'tcl9tk90.dll'), 'build_cache/tk.zip') if not os.path.exists('build_cache/tk.zip') else None"

REM Construção do executável otimizado com Nuitka via uv
uv run --with nuitka python -m nuitka ^
  --standalone ^
  --onefile ^
  --enable-plugin=tk-inter ^
  --tcl-library-dir=build_cache/tcl.zip ^
  --tk-library-dir=build_cache/tk.zip ^
  --windows-console-mode=disable ^
  --onefile-windows-splash-screen-image=src/sei_anonimizer/loading.png ^
  --include-package=sei_anonimizer ^
  --include-package=pymupdf ^
  --include-package=docx ^
  --include-distribution-metadata=sei-anonimizer ^
  --nofollow-import-to=spacy ^
  --assume-yes-for-downloads ^
  --output-dir=dist_nuitka ^
  --output-filename=sei-anonimizer.exe ^
  src/sei_anonimizer/main.py

REM Limpeza de builds anteriores e geração dos novos pacotes (wheel e sdist) via uv
if exist dist\*.whl del /q dist\*.whl
if exist dist\*.tar.gz del /q dist\*.tar.gz
uv build

REM Publicação no PyPI:
REM uv publish