import unittest
from unittest.mock import MagicMock, patch
from agno.embedder.google import GeminiEmbedder
from agno.media import Image, Audio, Video, File

class TestGeminiEmbedder(unittest.TestCase):
    def setUp(self):
        self.api_key = "test-api-key"
        self.embedder = GeminiEmbedder(api_key=self.api_key)
        # Mock the genai client
        self.mock_client = MagicMock()
        self.embedder.gemini_client = self.mock_client

    def test_get_embedding(self):
        # Mock response
        mock_embedding = MagicMock()
        mock_embedding.values = [0.1, 0.2, 0.3]
        mock_response = MagicMock()
        mock_response.embeddings = [mock_embedding]
        self.mock_client.models.embed_content.return_value = mock_response

        embedding = self.embedder.get_embedding("hello world")
        
        self.assertEqual(embedding, [0.1, 0.2, 0.3])
        self.mock_client.models.embed_content.assert_called_once()
        args, kwargs = self.mock_client.models.embed_content.call_args
        self.assertEqual(kwargs["contents"], "hello world")
        self.assertEqual(kwargs["model"], "gemini-embedding-2-preview")

    def test_get_embeddings_batch(self):
        # Mock response
        mock_e1 = MagicMock()
        mock_e1.values = [0.1, 0.2]
        mock_e2 = MagicMock()
        mock_e2.values = [0.3, 0.4]
        mock_response = MagicMock()
        mock_response.embeddings = [mock_e1, mock_e2]
        self.mock_client.models.embed_content.return_value = mock_response

        embeddings = self.embedder.get_embeddings(["text1", "text2"])
        
        self.assertEqual(embeddings, [[0.1, 0.2], [0.3, 0.4]])
        self.mock_client.models.embed_content.assert_called_once()
        args, kwargs = self.mock_client.models.embed_content.call_args
        self.assertEqual(kwargs["contents"], ["text1", "text2"])

    @patch("agno.utils.gemini.format_image_for_message")
    def test_get_multimodal_embedding_image(self, mock_format_image):
        mock_format_image.return_value = {"mime_type": "image/jpeg", "data": b"bytes"}
        
        mock_embedding = MagicMock()
        mock_embedding.values = [0.5, 0.6]
        mock_response = MagicMock()
        mock_response.embeddings = [mock_embedding]
        self.mock_client.models.embed_content.return_value = mock_response

        img = Image(content=b"bytes")
        embedding = self.embedder.get_multimodal_embedding(img)
        
        self.assertEqual(embedding, [0.5, 0.6])
        self.mock_client.models.embed_content.assert_called_once()
        
    def test_get_multimodal_embedding_audio(self):
        mock_embedding = MagicMock()
        mock_embedding.values = [0.7, 0.8]
        mock_response = MagicMock()
        mock_response.embeddings = [mock_embedding]
        self.mock_client.models.embed_content.return_value = mock_response

        audio = Audio(content=b"audiobytes", format="mp3")
        embedding = self.embedder.get_multimodal_embedding(audio)
        
        self.assertEqual(embedding, [0.7, 0.8])
        args, kwargs = self.mock_client.models.embed_content.call_args
        # kwargs["contents"] should be a Part object
        self.mock_client.models.embed_content.assert_called_once()

if __name__ == "__main__":
    unittest.main()
