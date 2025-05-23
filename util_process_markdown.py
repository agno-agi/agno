import os
# Importar loaders e splitters
from langchain_community.document_loaders import DirectoryLoader, UnstructuredMarkdownLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
# Importar embeddings e vectorstore
from langchain_openai import OpenAIEmbeddings
from langchain_community.vectorstores import Chroma

# --- Configurações ---
# Defina o caminho para a sua pasta contendo os arquivos Markdown
# Certifique-se de que esta pasta exista e contenha arquivos .md
FOLDER_PATH = "./Knowledge/md" 

# Configurar a API Key da OpenAI
# É recomendado carregar a chave de variáveis de ambiente por segurança
# Certifique-se de ter a variável de ambiente OPENAI_API_KEY configurada
# Ex: os.environ["OPENAI_API_KEY"] = "sua_chave_aqui"
# Se você não quiser definir a variável de ambiente, pode descomentar e definir a linha abaixo (não recomendado em produção)
# os.environ["OPENAI_API_KEY"] = "COLOQUE_SUA_CHAVE_DA_OPENAI_AQUI"

# Verifique se a variável de ambiente está configurada
if "OPENAI_API_KEY" not in os.environ:
    print("Erro: A variável de ambiente OPENAI_API_KEY não está configurada.")
    print("Por favor, defina a variável de ambiente ou descomente a linha 'os.environ[\"OPENAI_API_KEY\"] = ...' e insira sua chave.")
    exit() # Saia do script se a chave não estiver configurada
else:
    print("Chave da OpenAI configurada com sucesso.")

# --- Passo 1: Carregar os arquivos Markdown ---
print(f"Carregando arquivos Markdown da pasta: {FOLDER_PATH}")

# Use DirectoryLoader para carregar todos os arquivos .md na pasta e subpastas
# glob='**/*.md' busca recursivamente arquivos com extensão .md
try:
    loader = DirectoryLoader(
        FOLDER_PATH,
        glob='**/*.md',
        loader_cls=UnstructuredMarkdownLoader,
        show_progress=True # Mostra o progresso do carregamento
    )
    documents = loader.load()
    print(f"Carregados {len(documents)} documentos.")

except Exception as e:
    print(f"Erro ao carregar documentos: {e}")
    print(f"Certifique-se de que a pasta '{FOLDER_PATH}' existe e contém arquivos .md.")
    exit() # Saia se houver erro no carregamento

# --- Passo 2: Dividir os documentos em chunks ---
print("Dividindo documentos em chunks...")

# Configurações para o text splitter
chunk_size = 1000  # Tamanho máximo de cada chunk
chunk_overlap = 500 # Quantidade de texto sobreposto entre chunks para manter contexto

text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=chunk_size,
    chunk_overlap=chunk_overlap,
    length_function=len, # Usa a função len para medir o tamanho do chunk
    add_start_index=True # Adiciona o índice inicial do chunk no documento original
)

chunks = text_splitter.split_documents(documents)
print(f"Dividido em {len(chunks)} chunks.")

# --- Passo 3: Gerar Embeddings ---
print("Gerando embeddings para os chunks...")

# Use OpenAIEmbeddings para gerar os embeddings
embeddings = OpenAIEmbeddings()

# --- Passo 4: Criar o Vector Store e o Retriever ---
print("Criando Vector Store (Chroma) e o Retriever...")

# Criar uma instância do Chroma a partir dos chunks e embeddings
# Isso constrói o banco de dados vetorial em memória
# Para persistir em disco, adicione o parâmetro persist_directory="caminho/para/salvar"
vectorstore = Chroma.from_documents(
    documents=chunks,
    embedding=embeddings,
    persist_directory="./Knowledge/chroma_db", # Diretório para persistir o banco de dados
)

# Criar um retriever a partir do vector store
# O 'search_kwargs={"k": 5}' configura para buscar os 5 chunks mais relevantes por padrão
retriever = vectorstore.as_retriever(search_kwargs={"k": 5})

print("Processo concluído.")