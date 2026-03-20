import json
import shutil
import tempfile
import uuid
from pathlib import Path

import pytest

from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.docling_reader import DoclingReader
from agno.vectordb.chroma import ChromaDb

# Audio/video tests require openai-whisper (pip install openai-whisper) and system ffmpeg
try:
    import whisper  # noqa: F401

    _has_whisper = True
except ImportError:
    _has_whisper = False

_has_ffmpeg = shutil.which("ffmpeg") is not None
_has_audio_deps = _has_whisper and _has_ffmpeg


@pytest.fixture
def setup_vector_db():
    """Setup a temporary vector DB for testing."""
    vector_db = ChromaDb(
        collection=f"docling_vectors_{uuid.uuid4().hex}", path="tmp/chromadb_docling", persistent_client=True
    )
    yield vector_db
    # Clean up after test
    vector_db.drop()


def get_test_data_dir():
    """Get the path to the test data directory"""
    return Path(__file__).parent / "data"


def get_cookbook_data_dir():
    """Get the path to the cookbook test data directory"""
    repo_root = Path(__file__).parent.parent.parent.parent.parent.parent
    return repo_root / "cookbook" / "07_knowledge" / "testing_resources"


def get_filtered_data_dir():
    """Get the path to the filtered test data directory."""
    return Path(__file__).parent / "data" / "filters"


def prepare_knowledge_base(setup_vector_db, output_format="markdown"):
    """Prepare a knowledge base with filtered data."""
    kb = Knowledge(vector_db=setup_vector_db)

    kb.insert(
        path=get_filtered_data_dir() / "cv_1.pdf",
        reader=DoclingReader(output_format=output_format),
        metadata={"user_id": "jordan_mitchell", "document_type": "cv", "experience_level": "entry"},
    )
    kb.insert(
        path=get_filtered_data_dir() / "cv_2.pdf",
        reader=DoclingReader(output_format=output_format),
        metadata={"user_id": "taylor_brooks", "document_type": "cv", "experience_level": "mid"},
    )

    return kb


async def aprepare_knowledge_base(setup_vector_db, output_format="markdown"):
    """Asynchronously prepare a knowledge base with filtered data."""
    kb = Knowledge(vector_db=setup_vector_db)

    await kb.ainsert(
        path=get_filtered_data_dir() / "cv_1.pdf",
        reader=DoclingReader(output_format=output_format),
        metadata={"user_id": "jordan_mitchell", "document_type": "cv", "experience_level": "entry"},
    )
    await kb.ainsert(
        path=get_filtered_data_dir() / "cv_2.pdf",
        reader=DoclingReader(output_format=output_format),
        metadata={"user_id": "taylor_brooks", "document_type": "cv", "experience_level": "mid"},
    )

    return kb


def test_docling_knowledge_base_pdf_markdown(setup_vector_db):
    """Test loading a PDF with DoclingReader using markdown output."""
    pdf_file = get_test_data_dir() / "thai_recipes_short.pdf"

    kb = Knowledge(vector_db=setup_vector_db)
    kb.insert(
        path=pdf_file,
        reader=DoclingReader(output_format="markdown"),
    )

    assert setup_vector_db.exists()
    assert setup_vector_db.get_count() > 0

    agent = Agent(knowledge=kb, search_knowledge=True)
    response = agent.run("What are the Thai recipes mentioned?", markdown=True)

    tool_calls = []
    for msg in response.messages:
        if msg.tool_calls:
            tool_calls.extend(msg.tool_calls)

    function_calls = [call for call in tool_calls if call.get("type") == "function"]
    assert any(call["function"]["name"] == "search_knowledge_base" for call in function_calls)


@pytest.mark.asyncio
async def test_docling_knowledge_base_async_pdf(setup_vector_db):
    """Test asynchronously loading a PDF with DoclingReader."""
    pdf_file = get_test_data_dir() / "thai_recipes_short.pdf"

    kb = Knowledge(vector_db=setup_vector_db)
    await kb.ainsert(
        path=pdf_file,
        reader=DoclingReader(output_format="text"),
    )

    assert await setup_vector_db.async_exists()
    assert setup_vector_db.get_count() > 0

    agent = Agent(knowledge=kb, search_knowledge=True)
    response = await agent.arun("What Thai dishes are in the recipes?", markdown=True)

    tool_calls = []
    for msg in response.messages:
        if msg.tool_calls:
            tool_calls.extend(msg.tool_calls)

    function_calls = [call for call in tool_calls if call.get("type") == "function"]
    assert any(call["function"]["name"] == "search_knowledge_base" for call in function_calls)


def test_docling_knowledge_base_docx(setup_vector_db):
    """Test loading a DOCX file with DoclingReader."""
    docx_file = get_test_data_dir() / "sample.docx"

    kb = Knowledge(vector_db=setup_vector_db)
    kb.insert(
        path=docx_file,
        reader=DoclingReader(),
    )

    assert setup_vector_db.exists()
    assert setup_vector_db.get_count() > 0

    agent = Agent(knowledge=kb, search_knowledge=True)
    response = agent.run("What is the story of little prince about?", markdown=True)

    assert any(term in response.content for term in ["little prince", "prince", "planet", "rose"])


def test_docling_knowledge_base_with_metadata(setup_vector_db):
    """Test loading documents with metadata"""
    kb = prepare_knowledge_base(setup_vector_db)

    assert setup_vector_db.exists()
    assert setup_vector_db.get_count() > 0

    agent = Agent(knowledge=kb)
    response = agent.run(
        "Tell me about Jordan Mitchell's experience?", knowledge_filters={"user_id": "jordan_mitchell"}, markdown=True
    )

    assert "jordan" in response.content.lower()


@pytest.mark.asyncio
async def test_docling_knowledge_base_async_with_metadata(setup_vector_db):
    """Test asynchronously loading documents with metadata"""
    kb = await aprepare_knowledge_base(setup_vector_db, output_format="text")

    assert await setup_vector_db.async_exists()
    assert setup_vector_db.get_count() > 0

    agent = Agent(knowledge=kb, knowledge_filters={"user_id": "taylor_brooks"})
    response = await agent.arun("Tell me about the candidate's experience?", markdown=True)

    assert any(
        lang in response.content.lower()
        for lang in ["taylor", "developer", "docker", "kubernetes", "angular", "engineer", "software"]
    )


def test_docling_knowledge_base_with_chunking(setup_vector_db):
    """Test that DoclingReader chunking works correctly with Knowledge."""
    from agno.knowledge.chunking.document import DocumentChunking

    kb = Knowledge(vector_db=setup_vector_db)

    kb.insert(
        path=get_test_data_dir() / "thai_recipes_short.pdf",
        reader=DoclingReader(chunking_strategy=DocumentChunking(chunk_size=1000)),
    )

    assert setup_vector_db.exists()
    assert setup_vector_db.get_count() > 1

    collection = setup_vector_db.client.get_collection(name=setup_vector_db.collection_name)
    result = collection.get()

    documents = result.get("documents", [])

    # Validate that multiple chunk exists
    assert len(documents) > 10

    agent = Agent(knowledge=kb, search_knowledge=True)
    response = agent.run("List the Thai recipes", markdown=True)

    assert "thai" in response.content.lower()


def test_docling_knowledge_base_json_output(setup_vector_db):
    """Test DoclingReader with JSON output format."""
    kb = Knowledge(vector_db=setup_vector_db)

    kb.insert(
        path=get_filtered_data_dir() / "cv_1.pdf",
        reader=DoclingReader(output_format="json", chunk=False),
    )

    assert setup_vector_db.exists()
    assert setup_vector_db.get_count() > 0

    collection = setup_vector_db.client.get_collection(name=setup_vector_db.collection_name)
    result = collection.get()

    documents = result.get("documents", [])
    assert len(documents) == 1

    parsed = json.loads(documents[0])
    assert isinstance(parsed, dict)

    agent = Agent(knowledge=kb, search_knowledge=True)
    response = agent.run("What programming languages does the candidate know?", markdown=True)

    assert any(lang in response.content.lower() for lang in ["python", "react", "git", "html", "javascript"])


def test_docling_knowledge_base_pdf_url(setup_vector_db):
    """Test DoclingReader with URL input."""
    kb = Knowledge(vector_db=setup_vector_db)

    kb.insert(
        url="https://agno-public.s3.amazonaws.com/recipes/thai_recipes_short.pdf",
        reader=DoclingReader(),
    )

    agent = Agent(knowledge=kb, search_knowledge=True)
    response = agent.run("What ingredients do I need for Tom Kha Gai?", markdown=True)

    assert any(ingredient in response.content.lower() for ingredient in ["coconut", "chicken", "galangal"])

    tool_calls = []
    for msg in response.messages:
        if msg.tool_calls:
            tool_calls.extend(msg.tool_calls)

    function_calls = [call for call in tool_calls if call.get("type") == "function"]
    assert any(call["function"]["name"] == "search_knowledge_base" for call in function_calls)


def test_docling_knowledge_base_arxiv_url(setup_vector_db):
    """Test DoclingReader with URL input."""
    kb = Knowledge(vector_db=setup_vector_db)

    kb.insert(
        url="https://arxiv.org/pdf/2408.09869",
        reader=DoclingReader(),
    )

    agent = Agent(knowledge=kb, search_knowledge=True)
    response = agent.run("What does docling do", markdown=True)

    assert any(term in response.content.lower() for term in ["docling", "pdf", "convert"])


@pytest.mark.asyncio
async def test_docling_knowledge_base_async_url(setup_vector_db):
    """Test DoclingReader with URL input asynchronously."""
    kb = Knowledge(vector_db=setup_vector_db)

    await kb.ainsert(
        url="https://agno-public.s3.amazonaws.com/recipes/thai_recipes_short.pdf",
        reader=DoclingReader(output_format="text"),
    )

    agent = Agent(knowledge=kb, search_knowledge=True)
    response = await agent.arun("What ingredients do I need for Tom Kha Gai?", markdown=True)

    assert any(ingredient in response.content.lower() for ingredient in ["coconut", "chicken", "galangal"])

    tool_calls = []
    for msg in response.messages:
        if msg.tool_calls:
            tool_calls.extend(msg.tool_calls)

    function_calls = [call for call in tool_calls if call.get("type") == "function"]
    assert any(call["function"]["name"] == "search_knowledge_base" for call in function_calls)


def test_docling_invalid_url(setup_vector_db):
    """Test handling of invalid URL input."""
    kb = Knowledge(vector_db=setup_vector_db)

    with pytest.raises(Exception):
        kb.insert(
            url="https://invalid-url-does-not-exist.com/file.pdf",
            reader=DoclingReader(),
        )


def test_docling_invalid_output_format(setup_vector_db):
    """Test invalid DoclingReader output format."""
    kb = Knowledge(vector_db=setup_vector_db)

    with pytest.raises(ValueError):
        kb.insert(
            path=get_test_data_dir() / "thai_recipes_short.pdf",
            reader=DoclingReader(output_format="invalid_format"),
        )


def test_docling_knowledge_base_pptx(setup_vector_db):
    """Test loading a PPTX file with DoclingReader."""
    pptx_file = get_cookbook_data_dir() / "ai_presentation.pptx"

    kb = Knowledge(vector_db=setup_vector_db)
    kb.insert(
        path=pptx_file,
        reader=DoclingReader(),
    )

    assert setup_vector_db.exists()
    assert setup_vector_db.get_count() > 0

    agent = Agent(knowledge=kb, search_knowledge=True)
    response = agent.run("What are the main topics covered in the AI presentation?", markdown=True)

    assert any(term in response.content.lower() for term in ["ai", "artificial intelligence", "machine learning"])


def test_docling_knowledge_base_dotx(setup_vector_db):
    """Test loading a DOTX template file with DoclingReader."""
    dotx_file = get_cookbook_data_dir() / "meeting_notes_template.dotx"

    kb = Knowledge(vector_db=setup_vector_db)
    kb.insert(
        path=dotx_file,
        reader=DoclingReader(output_format="text"),
    )

    assert setup_vector_db.exists()
    assert setup_vector_db.get_count() > 0

    agent = Agent(knowledge=kb, search_knowledge=True)
    response = agent.run("What sections are included in the meeting notes template?", markdown=True)

    assert any(term in response.content.lower() for term in ["meeting", "template", "notes", "agenda"])


def test_docling_knowledge_base_jpeg(setup_vector_db):
    """Test loading a JPEG invoice image with DoclingReader."""
    jpeg_file = get_cookbook_data_dir() / "restaurant_invoice.jpeg"

    kb = Knowledge(vector_db=setup_vector_db)
    kb.insert(
        path=jpeg_file,
        reader=DoclingReader(output_format="text"),
    )

    assert setup_vector_db.exists()
    assert setup_vector_db.get_count() > 0

    agent = Agent(knowledge=kb, search_knowledge=True)
    response = agent.run("What is the total amount on the restaurant invoice?", markdown=True)

    assert any(term in response.content.lower() for term in ["41.57", "total", "invoice"])


def test_docling_knowledge_base_png(setup_vector_db):
    """Test loading a PNG order summary image with DoclingReader."""
    png_file = get_cookbook_data_dir() / "restaurant_invoice.png"

    kb = Knowledge(vector_db=setup_vector_db)
    kb.insert(
        path=png_file,
        reader=DoclingReader(),
    )

    assert setup_vector_db.exists()
    assert setup_vector_db.get_count() > 0

    agent = Agent(knowledge=kb, search_knowledge=True)
    response = agent.run("What items were ordered according to the order summary?", markdown=True)

    assert any(term in response.content.lower() for term in ["pizza", "burger", "coke"])


@pytest.mark.skipif(not _has_audio_deps, reason="openai-whisper or ffmpeg not installed")
def test_docling_knowledge_base_wav(setup_vector_db):
    """Test loading a WAV audio file with DoclingReader."""
    wav_file = get_cookbook_data_dir() / "agno_description.wav"

    kb = Knowledge(vector_db=setup_vector_db)
    kb.insert(
        path=wav_file,
        reader=DoclingReader(output_format="html"),
    )

    assert setup_vector_db.exists()
    assert setup_vector_db.get_count() > 0

    agent = Agent(knowledge=kb, search_knowledge=True)
    response = agent.run("What does the audio describe about Agno?", markdown=True)

    assert any(term in response.content.lower() for term in ["agno", "framework", "python", "agent"])


@pytest.mark.skipif(not _has_audio_deps, reason="openai-whisper or ffmpeg not installed")
def test_docling_knowledge_base_mp3(setup_vector_db):
    """Test loading an MP3 audio file with DoclingReader."""
    mp3_file = get_cookbook_data_dir() / "agno_description.mp3"

    kb = Knowledge(vector_db=setup_vector_db)
    kb.insert(
        path=mp3_file,
        reader=DoclingReader(),
    )

    assert setup_vector_db.exists()
    assert setup_vector_db.get_count() > 0

    agent = Agent(knowledge=kb, search_knowledge=True)
    response = agent.run("Summarize what Agno framework is used for", markdown=True)

    assert any(term in response.content.lower() for term in ["agno", "framework", "python", "agent"])


@pytest.mark.skipif(not _has_audio_deps, reason="openai-whisper or ffmpeg not installed")
def test_docling_knowledge_base_mp4(setup_vector_db):
    """Test loading an MP4 audio file with DoclingReader using VTT output."""
    mp4_file = get_cookbook_data_dir() / "agno_description.mp4"

    kb = Knowledge(vector_db=setup_vector_db)
    kb.insert(
        path=mp4_file,
        reader=DoclingReader(output_format="vtt"),
    )

    assert setup_vector_db.exists()
    assert setup_vector_db.get_count() > 0

    agent = Agent(knowledge=kb, search_knowledge=True)
    response = agent.run("What are the key features of Agno mentioned in the audio?", markdown=True)

    assert any(term in response.content.lower() for term in ["agno", "framework", "python", "agent"])


def test_docling_knowledge_base_xlsx_html_output(setup_vector_db):
    """Test loading an XLSX file with DoclingReader using HTML output."""
    try:
        import openpyxl
    except ImportError as e:
        raise ImportError("`openpyxl` not installed. Please install it via `pip install openpyxl`.") from e

    with tempfile.TemporaryDirectory() as temp_dir:
        xlsx_path = Path(temp_dir) / "products.xlsx"
        wb = openpyxl.Workbook()
        sheet = wb.active

        rows = [
            ["name", "category", "price"],
            ["Wireless Mouse", "Electronics", 29.99],
            ["Desk Lamp", "Home Office", 45.00],
            ["USB-C Cable", "Electronics", 12.99],
        ]

        for row in rows:
            sheet.append(row)

        wb.save(xlsx_path)
        wb.close()

        kb = Knowledge(vector_db=setup_vector_db)
        kb.insert(
            path=str(xlsx_path),
            reader=DoclingReader(output_format="html"),
        )

        assert setup_vector_db.exists()
        assert setup_vector_db.get_count() > 0

        agent = Agent(knowledge=kb, search_knowledge=True)
        response = agent.run("What products are available and what are their prices?", markdown=True)

        assert any(term in response.content.lower() for term in ["product", "price", "mouse", "lamp"])


def test_docling_knowledge_base_xml_uspto(setup_vector_db):
    """Test loading a USPTO XML patent file with DoclingReader."""
    with tempfile.TemporaryDirectory() as temp_dir:
        xml_path = Path(temp_dir) / "patent.xml"
        xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE us-patent-application SYSTEM "us-patent-application-v46-2022-12-01.dtd">
<us-patent-application lang="EN" dtd-version="v4.6 2022-12-01" file="US20230001234A1-20230101.XML" status="PRODUCTION" id="us-patent-application" country="US" date-produced="20230101" date-publ="20230101">
    <us-bibliographic-data-application lang="EN" country="US">
        <publication-reference>
            <document-id>
                <country>US</country>
                <doc-number>20230001234</doc-number>
                <kind>A1</kind>
                <date>20230101</date>
            </document-id>
        </publication-reference>
        <application-reference appl-type="utility">
            <document-id>
                <country>US</country>
                <doc-number>17123456</doc-number>
                <date>20220701</date>
            </document-id>
        </application-reference>
        <invention-title id="d2e43">Artificial Intelligence System for Data Analysis</invention-title>
        <parties>
            <applicants>
                <applicant sequence="001" app-type="applicant" designation="us-only">
                    <addressbook>
                        <last-name>Smith</last-name>
                        <first-name>John</first-name>
                        <address>
                            <city>San Jose</city>
                            <state>CA</state>
                            <country>US</country>
                        </address>
                    </addressbook>
                </applicant>
            </applicants>
            <inventors>
                <inventor sequence="001" designation="us-only">
                    <addressbook>
                        <last-name>Smith</last-name>
                        <first-name>John</first-name>
                    </addressbook>
                </inventor>
            </inventors>
        </parties>
    </us-bibliographic-data-application>
    <abstract id="abstract">
        <p id="p-0001">An artificial intelligence system for analyzing and processing complex datasets using advanced machine learning algorithms and neural networks.</p>
    </abstract>
    <description id="description">
        <heading id="h-0001" level="1">TECHNICAL FIELD</heading>
        <p id="p-0002">This invention relates to artificial intelligence systems for data analysis and processing.</p>
        <heading id="h-0002" level="1">BACKGROUND</heading>
        <p id="p-0003">Traditional data analysis methods are insufficient for modern large-scale datasets.</p>
        <heading id="h-0003" level="1">SUMMARY</heading>
        <p id="p-0004">The invention provides an AI system with improved processing capabilities using neural networks.</p>
    </description>
    <claims id="claims">
        <claim id="CLM-00001" num="00001">
            <claim-text>An artificial intelligence system comprising neural networks for data analysis.</claim-text>
        </claim>
    </claims>
</us-patent-application>"""

        xml_path.write_text(xml_content)

        kb = Knowledge(vector_db=setup_vector_db)
        kb.insert(
            path=str(xml_path),
            reader=DoclingReader(),
        )

        assert setup_vector_db.exists()
        assert setup_vector_db.get_count() > 0

        agent = Agent(knowledge=kb, search_knowledge=True)
        response = agent.run("What is the patent patent.xml about?", markdown=True)

        assert any(term in response.content.lower() for term in ["artificial intelligence", "ai", "data", "neural"])


def test_docling_knowledge_base_latex(setup_vector_db):
    """Test loading a LaTeX file with DoclingReader."""
    with tempfile.TemporaryDirectory() as temp_dir:
        tex_path = Path(temp_dir) / "research.tex"
        tex_content = r"""\documentclass{article}
\usepackage{amsmath}

\title{Advanced Machine Learning Techniques}
\author{Dr. Sarah Johnson}
\date{March 2026}

\begin{document}

\maketitle

\begin{abstract}
This paper presents novel approaches to improving natural language processing models
through advanced machine learning techniques. We demonstrate significant improvements
in performance across multiple benchmarks.
\end{abstract}

\section{Introduction}

Natural Language Processing (NLP) has seen remarkable progress in recent years,
driven primarily by the development of large-scale transformer models.

\subsection{Challenges}

Several challenges remain:
\begin{itemize}
    \item Computational efficiency
    \item Model interpretability
    \item Cross-lingual transfer learning
\end{itemize}

\section{Methodology}

Our approach employs a modified transformer architecture with attention mechanism:
\begin{equation}
    Attention(Q, K, V) = softmax\left(\frac{QK^T}{\sqrt{d_k}}\right)V
\end{equation}

\section{Results}

Our experimental results demonstrate significant improvements across all benchmarks.

\end{document}"""

        tex_path.write_text(tex_content)

        kb = Knowledge(vector_db=setup_vector_db)
        kb.insert(
            path=str(tex_path),
            reader=DoclingReader(output_format="text"),
        )

        assert setup_vector_db.exists()
        assert setup_vector_db.get_count() > 0

        agent = Agent(knowledge=kb, search_knowledge=True)
        response = agent.run("What is the research paper research.tex about?", markdown=True)

        assert any(
            term in response.content.lower() for term in ["machine", "learning", "nlp", "language", "transformer"]
        )


def test_docling_knowledge_base_html(setup_vector_db):
    """Test loading an HTML file with DoclingReader."""
    with tempfile.TemporaryDirectory() as temp_dir:
        html_path = Path(temp_dir) / "company.html"
        html_content = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>TechVision AI - Company Overview</title>
</head>
<body>
    <h1>TechVision AI - Innovating the Future</h1>

    <section id="overview">
        <h2>Company Overview</h2>
        <p>
            TechVision AI is a leading artificial intelligence company founded in 2018
            with the mission to democratize AI technology and make it accessible to
            businesses of all sizes. Headquartered in San Francisco, California.
        </p>
    </section>

    <section id="products">
        <h2>Our Products</h2>
        <ul>
            <li><strong>AI Studio Pro:</strong> Development environment for ML models</li>
            <li><strong>DataFlow Analytics:</strong> Real-time data processing platform</li>
            <li><strong>Vision AI:</strong> Computer vision solutions</li>
        </ul>
    </section>

    <section id="team">
        <h2>Leadership Team</h2>
        <div>
            <h3>Dr. Emily Rodriguez - CEO</h3>
            <p>Former Stanford AI researcher with 15 years of experience in machine learning.</p>
        </div>
        <div>
            <h3>James Park - CTO</h3>
            <p>Previously led AI engineering teams at Google and Amazon.</p>
        </div>
    </section>
</body>
</html>"""

        html_path.write_text(html_content)

        kb = Knowledge(vector_db=setup_vector_db)
        kb.insert(
            path=str(html_path),
            reader=DoclingReader(output_format="json"),
        )

        assert setup_vector_db.exists()
        assert setup_vector_db.get_count() > 0

        agent = Agent(knowledge=kb, search_knowledge=True)
        response = agent.run("Who are the members of the leadership team?", markdown=True)

        assert any(term in response.content.lower() for term in ["emily", "rodriguez", "james", "park"])
