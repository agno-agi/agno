from langchain.document_loaders import DirectoryLoader

DATA_PATH = "Knowledge"

def load_documents():
    loader = DirectoryLoader(DATA_PATH, glob="*.md")
    documets = loader.load()
    return documents

def text_splitter = RecursiveCharacterTextSplitter(
        chunk_size - 1000,
        chunk_overlap = 500,
        length_function = len,
        add_start_index = True)

    chunks = text_splitter.split_documents(documents)
    return chunks