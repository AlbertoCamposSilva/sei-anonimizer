pyinstaller --noconfirm --onefile --windowed `
    --add-data "src/anonimizer/dic_nomes.csv;." `
    --add-data "src/anonimizer/dic_sobrenomes.csv;." `
    --add-data "src/anonimizer/dic_stopwords.csv;." `
    --paths "src/anonimizer" `
    "src/anonimizer/anonimizer.py"