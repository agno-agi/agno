from docling.document_converter import DocumentConverter
import os

# Define as pastas de origem e destino
source_folder = 'Knowledge/PDF'
dest_folder = 'Knowledge/md'

# --- Configuração Inicial ---

# Garante que a pasta de destino exista. Se não existir, ela será criada.
# exist_ok=True evita erro se a pasta já existir.
os.makedirs(dest_folder, exist_ok=True)
print(f"Pasta de destino '{dest_folder}' verificada/criada.")

# Inicializa o conversor
try:
    converter = DocumentConverter()
    print("Conversor inicializado com sucesso.")
except Exception as e:
    print(f"Erro ao inicializar o conversor DocumentConverter: {e}")
    print("Certifique-se de que a biblioteca 'docling' está instalada corretamente.")
    exit() # Sai do script se o conversor não puder ser inicializado

# --- Processamento dos Arquivos ---

print(f"\nVerificando arquivos na pasta de origem: '{source_folder}'...")

files_in_source = os.listdir(source_folder)
print(f"Encontrados {len(files_in_source)} itens.")

# Filtra apenas arquivos que terminam com .pdf (case-insensitive)
# e garante que sejam realmente arquivos (não subpastas)
pdf_files = [f for f in files_in_source if f.lower().endswith('.pdf') and os.path.isfile(os.path.join(source_folder, f))]

print(f"Encontrados {len(pdf_files)} arquivos PDF prontos para processamento.")

if not pdf_files:
    print("Nenhum arquivo PDF encontrado na pasta de origem. Nada para converter.")

# Processa cada arquivo PDF encontrado
for pdf_filename in pdf_files:
    source_pdf_path = os.path.join(source_folder, pdf_filename)

    # Gera o nome do arquivo de destino .md
    # Remove a extensão .pdf e adiciona .md
    base_filename = os.path.splitext(pdf_filename)[0]
    md_filename = base_filename + '.md'
    dest_md_path = os.path.join(dest_folder, md_filename)

    print(f"\nProcessando '{pdf_filename}'...")

    # --- Verificação de Existência ---
    if os.path.exists(dest_md_path):
        print(f"Arquivo MD '{md_filename}' já existe em '{dest_folder}'. Pulando conversão para este arquivo.")
        # Não deleta o PDF neste caso, pois o MD correspondente já existe.
        continue # Passa para o próximo arquivo no loop

    # --- Conversão ---
    print(f"Arquivo MD '{md_filename}' não encontrado. Iniciando conversão...")
    try:
        # A documentação (ou exemplos) geralmente mostra que converter
        # um único arquivo é feito passando o caminho do arquivo para o método convert.
        # O script original parecia converter a pasta inteira, mas para controlar
        # arquivo por arquivo, é necessário converter um de cada vez.
        result = converter.convert(source_pdf_path)

        # --- Verificação e Salvamento do Resultado ---
        # Verifica se o resultado da conversão é válido e contém o documento exportável
        if result and hasattr(result, 'document') and hasattr(result.document, 'export_to_markdown'):
            markdown_content = result.document.export_to_markdown()

            # Salva o conteúdo Markdown no arquivo de destino
            with open(dest_md_path, 'w', encoding='utf-8') as f:
                f.write(markdown_content)
            print(f"\nConversão bem-sucedida. Arquivo salvo em '{dest_md_path}'.")

            # --- Exclusão do PDF Original ---
            try:
                os.remove(source_pdf_path)
                print(f"Arquivo PDF original '{pdf_filename}' excluído.")
            except OSError as e:
                print(f"Erro ao excluir arquivo PDF '{pdf_filename}': {e}")
            except Exception as e:
                 print(f"Erro inesperado ao excluir arquivo PDF '{pdf_filename}': {e}")


        else:
            # Isso pode ocorrer se a conversão falhou de alguma forma sem levantar uma exceção específica
            print(f"Erro na conversão de '{pdf_filename}': Resultado inválido ou sem documento exportável.")
            # O arquivo PDF original não é excluído neste caso.

    except Exception as e:
        # Captura qualquer erro durante o processo de conversão ou escrita do arquivo
        print(f"Erro durante o processamento (conversão ou salvamento) de '{pdf_filename}': {e}")
        # O arquivo PDF original não é excluído em caso de erro.

print("\n--- Processamento Concluído ---")
print(f"Verifique a pasta '{dest_folder}' para os arquivos .md convertidos.")