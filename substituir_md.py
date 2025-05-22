import os
import sys

# Define a pasta onde os arquivos .md estão localizados
folder_path = 'Knowledge/Pareceres'

# Define o caractere errado e o correto
wrong_char = '\n\n\n'
correct_char = '\n\n'

print(f"Iniciando correção de caracteres na pasta: {folder_path}")
print(f"Substituindo '{wrong_char}' por '{correct_char}' em arquivos .md...")

# Verifica se a pasta existe
if not os.path.exists(folder_path):
    print(f"Erro: A pasta '{folder_path}' não foi encontrada.")
    print("Certifique-se de que o script está sendo executado na mesma pasta que 'Knowledge'.")
    sys.exit(1) # Sai do script com código de erro

processed_count = 0
modified_count = 0

# Percorre todos os arquivos na pasta
try:
    for filename in os.listdir(folder_path):
        # Constrói o caminho completo para o arquivo
        filepath = os.path.join(folder_path, filename)

        # Verifica se é um arquivo e se termina com .md
        if os.path.isfile(filepath) and filename.endswith('.md'):
            processed_count += 1
            print(f"Processando arquivo: {filename}...")

            try:
                # Abre o arquivo para leitura (usando encoding UTF-8, que é comum para Markdown)
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read()

                # Realiza a substituição
                new_content = content.replace(wrong_char, correct_char)

                # Verifica se houve alguma mudança antes de escrever de volta
                if new_content != content:
                    # Abre o arquivo para escrita (sobrescreve o conteúdo original)
                    with open(filepath, 'w', encoding='utf-8') as f:
                        f.write(new_content)
                    modified_count += 1
                    print("  -> Corrigido com sucesso!")
                else:
                    print("  -> Nenhuma ocorrência do caractere errado encontrada neste arquivo.")

            except IOError as e:
                print(f"  Erro ao ler/escrever o arquivo {filename}: {e}")
            except Exception as e:
                print(f"  Ocorreu um erro inesperado ao processar {filename}: {e}")

except OSError as e:
    print(f"Erro ao listar arquivos na pasta {folder_path}: {e}")
    sys.exit(1)

print("\n--------------------")
print("Processamento concluído.")
print(f"Total de arquivos .md encontrados: {processed_count}")
print(f"Total de arquivos modificados: {modified_count}")
print("--------------------")