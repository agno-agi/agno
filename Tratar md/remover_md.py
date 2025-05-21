import os
import sys
import re # Importa o módulo de expressões regulares

# --- COLE O BLOCO DE TEXTO QUE VOCÊ QUER REMOVER AQUI ---
# Certifique-se de que o texto esteja exatamente como no exemplo que você quer remover.
# Use aspas triplas (simples ou duplas) para blocos multi-linha.
text_block_to_remove_literal = """
21.040-360
(21)3865-9585
E-mail:
cep@ini.fiocruz.br
Endereço:
Bairro:
CEP:
Telefone:
Avenida Brasil 4365
Manguinhos
UF: RJ
Município:
RIO DE JANEIRO
"""
# --- FIM DO BLOCO DE TEXTO A REMOVER ---


# Define a pasta onde os arquivos .md estão localizados
# Ajustado para verificar './Knowledge/teste' se './Knowledge' não existir
folder_path = './Knowledge/Pareceres'

print(f"Iniciando remoção de bloco de texto colado na pasta: {folder_path}")
print(f"Tentando remover o seguinte bloco de texto (ignorando espaçamento/newlines):\n---")
print(text_block_to_remove_literal.strip()) # Mostra o bloco que será buscado
print("---")


# --- Gera a Expressão Regular a partir do texto literal ---
# 1. Divide o texto literal em "palavras" ou "tokens" usando qualquer sequência de espaços/newlines como delimitador.
tokens = re.split(r'\s+', text_block_to_remove_literal)
# 2. Filtra quaisquer tokens vazios que podem resultar da divisão (ex: se o bloco começa/termina com \s+).
tokens = [token for token in tokens if token]
# 3. Escapa caracteres especiais de regex em cada token literal (ex: . vira \., ( vira \( ).
escaped_tokens = [re.escape(token) for token in tokens]
# 4. Junta os tokens escapados com '\s+' para permitir quebra de linha ou múltiplos espaços entre eles.
regex_pattern_string = r'\s*'.join(escaped_tokens) + r'\s*' # Adiciona \s* no início e fim para pegar espaços em volta

# Compila a expressão regular
# re.S (DOTALL) não é estritamente necessário pois \s já casa newlines, mas mal não faz.
# re.I (IGNORECASE) pode ser útil se a capitalização puder variar. Vamos adicioná-lo como opção.
text_block_pattern = re.compile(regex_pattern_string, re.S | re.I)


# --- Processamento dos Arquivos ---

processed_count = 0
modified_count = 0

# Percorre todos os arquivos na pasta e subpastas (usando os.walk)
try:
    for root, _, files in os.walk(folder_path):
        for filename in files:
            # Constrói o caminho completo para o arquivo
            filepath = os.path.join(root, filename)

            # Verifica se é um arquivo e se termina com .md
            if os.path.isfile(filepath) and filename.endswith('.md'):
                processed_count += 1
                #print(f"Processando arquivo: {filepath}...")

                try:
                    # Abre o arquivo para leitura (usando encoding UTF-8, que é comum para Markdown)
                    # Adicionando errors='ignore' para tentar lidar com possíveis caracteres problemáticos
                    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()

                    # Salva o conteúdo original para comparação posterior
                    original_content = content

                    # Aplica a remoção do bloco de texto usando a expressão regular
                    # Substitui o bloco encontrado por uma string vazia
                    content = text_block_pattern.sub('', content)

                    # Verifica se houve alguma mudança (se o bloco foi encontrado e removido)
                    if content != original_content:
                        # Abre o arquivo para escrita (sobrescreve o conteúdo original)
                        with open(filepath, 'w', encoding='utf-8') as f:
                            f.write(content)
                        modified_count += 1
                        #print("  -> Bloco de texto removido com sucesso!")
                    else:
                        print("  -> Bloco de texto específico não encontrado neste arquivo.")

                except IOError as e:
                    print(f"  Erro ao ler/escrever o arquivo {filepath}: {e}")
                except Exception as e:
                    print(f"  Ocorreu um erro inesperado ao processar {filepath}: {e}")

except OSError as e:
    print(f"Erro ao listar arquivos na pasta {folder_path}: {e}")
    sys.exit(1)

print("\n--------------------")
print("Processamento concluído.")
print(f"Total de arquivos .md encontrados: {processed_count}")
print(f"Total de arquivos modificados: {modified_count}")
print("--------------------")