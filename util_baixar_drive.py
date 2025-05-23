from docling.document_converter import DocumentConverter
import os
import time
import io
import tempfile # Para lidar com arquivos temporários

# Importações para a API do Google Drive
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload

# --- Configurações ---

# Se modificar estes SCOPES, delete o arquivo token.json.
SCOPES = ['https://www.googleapis.com/auth/drive'] # Escopo para acesso total ao Google Drive
CREDENTIALS_FILE = 'credentials.json' # Nome do seu arquivo de credenciais baixado
TOKEN_FILE = 'token.json'           # Arquivo onde as credenciais salvas serão armazenadas
GOOGLE_DRIVE_FOLDER_ID = '1qnm0ljEGQIwhqvdQe5I_Fm6cyF1J3Q_I' # ID da pasta do Google Drive

dest_folder = 'Knowledge/md' # Pasta de destino local para os arquivos .md

# --- Funções da API do Google Drive ---

def authenticate_google_drive():
    """Autentica com a API do Google Drive."""
    creds = None
    # O arquivo token.json armazena as credenciais do usuário de execuções anteriores
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    # Se não houver credenciais (válidas) disponíveis, permite que o usuário faça login.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            # Força o login no navegador (pode ser necessário se o token expirar ou escopos mudarem)
            # flow.redirect_uri = 'urn:ietf:wg:oauth:2.0:oob' # Use para ambiente sem navegador gráfico
            # auth_url, _ = flow.authorization_url(prompt='consent')
            # print(f'Por favor, visite esta URL para autorizar o aplicativo: {auth_url}')
            # code = input('Digite o código de autorização da página: ')
            # flow.fetch_token(code=code)
            creds = flow.run_local_server(port=0) # Abre o navegador automaticamente
        # Salva as credenciais para a próxima execução
        with open(TOKEN_FILE, 'w') as token:
            token.write(creds.to_json())
    return build('drive', 'v3', credentials=creds)

def list_pdf_files_in_folder(service, folder_id):
    """Lista arquivos PDF em uma pasta específica do Google Drive."""
    print(f"\nBuscando arquivos PDF na pasta do Google Drive com ID: {folder_id}...")
    results = []
    page_token = None
    query = f"'{folder_id}' in parents and mimeType='application/pdf' and trashed=false"
    try:
        while True:
            response = service.files().list(q=query,
                                            spaces='drive',
                                            fields='nextPageToken, files(id, name, parents)',
                                            pageToken=page_token).execute()
            results.extend(response.get('files', []))
            page_token = response.get('nextPageToken', None)
            if page_token is None:
                break
    except HttpError as error:
        print(f'Ocorreu um erro ao listar arquivos: {error}')
        return []
    
    print(f"Encontrados {len(results)} arquivos PDF no Google Drive.")
    return results

def download_file(service, file_id, file_name):
    """Baixa um arquivo do Google Drive para um arquivo temporário local."""
    print(f"Baixando '{file_name}'...")
    request = service.files().get_media(fileId=file_id)
    
    # Usa um arquivo temporário
    # delete=False permite fechar o arquivo antes de removê-lo explicitamente
    temp_file = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    temp_file_path = temp_file.name
    temp_file.close() # Fecha o handle para que MediaIoBaseDownload possa escrever

    try:
        with open(temp_file_path, 'wb') as f:
            downloader = MediaIoBaseDownload(f, request)
            done = False
            while done is False:
                status, done = downloader.next_chunk()
                print(f"  Download {int(status.progress() * 100)}%.", end='\r')
        print(f"\nDownload de '{file_name}' concluído para '{temp_file_path}'.")
        return temp_file_path
    except HttpError as error:
        print(f"\nErro ao baixar arquivo '{file_name}' ({file_id}): {error}")
        # Certifica-se de remover o arquivo temporário se o download falhar
        if os.path.exists(temp_file_path):
             os.remove(temp_file_path)
        return None
    except Exception as e:
        print(f"\nErro inesperado ao baixar arquivo '{file_name}' ({file_id}): {e}")
        if os.path.exists(temp_file_path):
             os.remove(temp_file_path)
        return None


def delete_file(service, file_id, file_name):
    """Deleta um arquivo do Google Drive."""
    print(f"Excluindo '{file_name}' ({file_id}) do Google Drive...")
    try:
        service.files().delete(fileId=file_id).execute()
        print(f"Arquivo '{file_name}' excluído do Google Drive.")
    except HttpError as error:
        print(f"Erro ao excluir arquivo '{file_name}' ({file_id}) do Google Drive: {error}")
    except Exception as e:
        print(f"Erro inesperado ao excluir arquivo '{file_name}' ({file_id}) do Google Drive: {e}")


# --- Script Principal ---

# Garante que a pasta de destino exista.
os.makedirs(dest_folder, exist_ok=True)
print(f"Pasta de destino local '{dest_folder}' verificada/criada.")

# Autentica com o Google Drive
drive_service = None
try:
    drive_service = authenticate_google_drive()
    print("Autenticação com o Google Drive bem-sucedida.")
except Exception as e:
    print(f"Erro durante a autenticação com o Google Drive: {e}")
    print("Certifique-se de ter o arquivo 'credentials.json' e que a API do Drive esteja ativada.")
    exit()

# Inicializa o conversor docling
converter = None
try:
    converter = DocumentConverter()
    print("Conversor docling inicializado com sucesso.")
except Exception as e:
    print(f"Erro ao inicializar o conversor DocumentConverter: {e}")
    print("Certifique-se de que a biblioteca 'docling' está instalada corretamente.")
    exit()

# Obtém a lista de arquivos PDF da pasta do Google Drive
pdf_files_from_drive = list_pdf_files_in_folder(drive_service, GOOGLE_DRIVE_FOLDER_ID)

if not pdf_files_from_drive:
    print("Nenhum arquivo PDF encontrado na pasta especificada do Google Drive. Nada para converter.")
else:
    # Processa cada arquivo PDF encontrado no Google Drive
    for drive_file_info in pdf_files_from_drive:
        file_id = drive_file_info['id']
        file_name = drive_file_info['name']

        print(f"\nProcessando arquivo do Drive: '{file_name}' (ID: {file_id})")

        # Gera o nome do arquivo de destino .md local
        base_filename = os.path.splitext(file_name)[0]
        md_filename = base_filename + '.md'
        dest_md_path = os.path.join(dest_folder, md_filename)

        # --- Verificação de Existência Local ---
        if os.path.exists(dest_md_path):
            print(f"Arquivo MD local '{md_filename}' já existe em '{dest_folder}'. Pulando conversão/download para este arquivo.")
            # O arquivo no Drive não é excluído neste caso, seguindo a lógica original
            # de não reprocessar se o destino já existe.
            continue # Passa para o próximo arquivo no loop

        # --- Download do Arquivo do Drive ---
        print(f"Arquivo MD local '{md_filename}' não encontrado. Baixando PDF do Drive...")
        temp_pdf_path = download_file(drive_service, file_id, file_name)

        if temp_pdf_path is None:
            print(f"Download de '{file_name}' falhou. Pulando processamento.")
            continue # Passa para o próximo arquivo no loop

        # --- Conversão Usando docling ---
        print(f"Iniciando conversão de '{file_name}' (baixado temporariamente para '{temp_pdf_path}')...")
        conversion_successful = False
        try:
            result = converter.convert(temp_pdf_path)

            # --- Verificação e Salvamento do Resultado ---
            if result and hasattr(result, 'document') and hasattr(result.document, 'export_to_markdown'):
                markdown_content = result.document.export_to_markdown()

                # Salva o conteúdo Markdown no arquivo de destino
                with open(dest_md_path, 'w', encoding='utf-8') as f:
                    f.write(markdown_content)
                print(f"Conversão bem-sucedida. Arquivo MD salvo em '{dest_md_path}'.")
                conversion_successful = True
            else:
                print(f"Erro na conversão de '{file_name}': Resultado inválido ou sem documento exportável.")

        except Exception as e:
            print(f"Erro durante o processamento (conversão ou salvamento) de '{file_name}': {e}")

        finally:
            # --- Limpeza do Arquivo PDF Temporário ---
            if os.path.exists(temp_pdf_path):
                try:
                    os.remove(temp_pdf_path)
                    print(f"Arquivo PDF temporário '{temp_pdf_path}' excluído.")
                except OSError as e:
                    print(f"Erro ao excluir arquivo PDF temporário '{temp_pdf_path}': {e}")

            # --- Exclusão do PDF Original do Drive (SOMENTE se a conversão foi bem-sucedida) ---
            if conversion_successful:
                delete_file(drive_service, file_id, file_name)
            else:
                 print(f"Conversão de '{file_name}' falhou ou MD local já existia. Arquivo mantido no Google Drive.")


        # Opcional: Adicionar um pequeno delay entre as conversões
        # time.sleep(1) # Descomente esta linha se precisar de um pequeno intervalo

print("\n--- Processamento Concluído ---")
print(f"Verifique a pasta local '{dest_folder}' para os arquivos .md convertidos.")