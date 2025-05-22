import sys
import sys
sys.path.insert(0, "/app") # Ensure /app is searched for modules

import pytest
from unittest.mock import patch, MagicMock

from agno.agent import Agent
from agno.models.google import Gemini
# Import GenerateContentResponse and related types for mocking
from google.genai.types import GenerateContentResponse, Candidate, Part, GenerateContentConfig


def test_gemini_flash_preview_hello_world(): # Renamed test function
  """Tests that the Gemini Flash preview model can respond to a simple prompt, with external call mocked."""
  print("TEST_LOG: Starting test_gemini_flash_preview_hello_world") # Updated log message

  # Create a MagicMock for the GenerateContentResponse
  mock_gen_content_response = MagicMock(spec=GenerateContentResponse)

  # Mock the 'candidates' attribute
  mock_candidate = MagicMock(spec=Candidate)
  mock_part = MagicMock(spec=Part)
  mock_part.text = "Mocked Hello World"
  # The 'content' attribute of a Candidate is a Content object, which has 'parts'.
  mock_content_obj = MagicMock() # Mock for google.genai.types.Content
  mock_content_obj.parts = [mock_part]
  mock_content_obj.role = 'model' # Role is part of the Content object
  mock_candidate.content = mock_content_obj
  mock_candidate.finish_reason = "STOP"
  mock_candidate.index = 0
  # Grounding metadata is accessed, so mock it if necessary
  mock_candidate.grounding_metadata = None # Or MagicMock() if specific attributes are accessed

  mock_gen_content_response.candidates = [mock_candidate]

  # Mock the 'usage_metadata' attribute
  mock_usage_metadata = MagicMock()
  mock_usage_metadata.prompt_token_count = 5
  mock_usage_metadata.candidates_token_count = 5
  mock_usage_metadata.total_token_count = 10
  mock_usage_metadata.cached_content_token_count = 0
  mock_gen_content_response.usage_metadata = mock_usage_metadata
  
  # If prompt_feedback is accessed, mock it as well
  mock_gen_content_response.prompt_feedback = None # Or MagicMock()

  # Patch 'google.genai.GenerativeModel.generate_content'
  # The actual client is obtained via self.get_client().models, so we target that path.
  # However, the client and model are instantiated dynamically.
  # It's often easier to patch the method on the class that will be instantiated.
  # The `Gemini` class in agno calls `self.get_client().models.generate_content`.
  # `self.get_client()` returns `genai.Client(...)`.
  # `genai.Client(...).models` returns a `ModelServiceClient` which has `generate_content`.
  # Or, if `genai.configure` was used, it might be `genai.GenerativeModel(...).generate_content`.
  # Let's try patching at the `google.genai.GenerativeModel` level first, as it's a common entry point.
  # If that doesn't work, we might need to patch `google.genai.Client(...).models.generate_content`
  # or `google.genai.client.GenerativeModel(...)`
  # Based on gemini.py, it's `self.get_client().models.generate_content`
  # `get_client()` returns `genai.Client()`. `genai.Client().models` is an accessor for `genai.GenerativeModel(model_name=...)`
  # So, we need to patch the `generate_content` method of `google.generativeai.GenerativeModel`.

  # We also need to patch google.genai.Client to prevent it from raising an error during initialization
  # if API keys are not found.
  mock_generative_model_instance = MagicMock()
  mock_generative_model_instance.generate_content.return_value = mock_gen_content_response

  # Mock the .models accessor on the Client instance to return our mock_generative_model_instance
  mock_client_instance = MagicMock()
  mock_client_instance.models = mock_generative_model_instance
  
  # It's google.genai.client.Client usually, but agno imports `from google import genai`
  # and then calls `genai.Client`. So we patch `google.genai.Client`.
  with patch('google.genai.Client', return_value=mock_client_instance) as mock_genai_client_constructor, \
       patch('google.generativeai.GenerativeModel.generate_content', return_value=mock_gen_content_response) as mock_sdk_generate_content:
    try:
      print("TEST_LOG: Initializing Agent with mocked Client and generate_content")
      gemini_model = Gemini(
          id="gemini-2.5-flash-preview-05-20",
          temperature=0.7,
          top_p=0.8,
          max_output_tokens=100
      )
      agent = Agent(
          model=gemini_model
      )
      print("TEST_LOG: Agent initialized. Sending 'Hello, world!' to agent.run()")
      run_response = agent.run(message="Hello, world!")
      print(f"TEST_LOG: Received RunResponse from agent.run(): {run_response}")
      response_content = run_response.content
      print(f"TEST_LOG: Received content from RunResponse: {response_content}")

      # Check that the generate_content method on our specific model mock was called.
      # This is because we mocked google.genai.Client to return an instance (mock_client_instance)
      # which has its 'models' attribute set to another mock (mock_generative_model_instance).
      # So, the call path is agent -> gemini_model.invoke -> get_client (returns mock_client_instance)
      # -> mock_client_instance.models (is mock_generative_model_instance)
      # -> mock_generative_model_instance.generate_content()
      mock_generative_model_instance.generate_content.assert_called_once()
      # mock_sdk_generate_content.assert_called_once() # This would fail as the original SDK path is bypassed by mock_genai_client_constructor

      # Verify that the mock was called with the correct generation_config
      args, kwargs = mock_generative_model_instance.generate_content.call_args
      if 'config' in kwargs:
          called_config = kwargs['config']
          assert called_config.temperature == 0.7
          assert called_config.top_p == 0.8
          assert called_config.max_output_tokens == 100
          print("TEST_LOG: Mock called with correct generation_config.")
      else:
          # If 'config' is not in kwargs, it might be that no specific generation_config was formed
          # This can happen if all params are default or None. However, we set them.
          # Let's check the passed arguments to the mock directly if this happens.
          # This part of the assertion might need adjustment based on how Gemini class passes params.
          # For now, we assume 'config' object is passed if non-default params are set.
          print(f"TEST_LOG: generate_content called with kwargs: {kwargs}")
          pytest.fail("generate_content was not called with a 'config' kwarg as expected when parameters are set.")


      assert response_content is not None, "Response content should not be None"
      assert isinstance(response_content, str), f"Response content should be a string, but got {type(response_content)}"
      assert response_content.strip() != "", "Response content should not be an empty string"
      assert response_content == "Mocked Hello World", "Response content should be the mocked content"
      print("TEST_LOG: Assertions passed.")
    except Exception as e:
      print(f"TEST_LOG: Test failed with error: {e}")
      raise
    finally:
      print("TEST_LOG: Finished test_gemini_flash_preview_hello_world") # Updated log message

if __name__ == "__main__":
    print("TEST_LOG: Running test_gemini_flash_preview_hello_world directly via __main__") # Updated log message
    try:
        test_gemini_flash_preview_hello_world() # Updated call
        print("TEST_LOG: test_gemini_flash_preview_hello_world completed via __main__.") # Updated log message
    except Exception as e:
        print(f"TEST_LOG: test_gemini_flash_preview_hello_world failed via __main__: {e}") # Updated log message
        import traceback
        traceback.print_exc()
