import unittest
from unittest.mock import MagicMock, patch
import sys
import os

# Add parent directory to path to import agent modules
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from agent.base import BaseHandler
from agent.gemini import GeminiHandler
# Attempt to import OpenAIHandler, but handle if openai is not installed
try:
    from agent.openai import OpenAIHandler
except ImportError:
    OpenAIHandler = None

class TestBaseHandler(unittest.TestCase):
    def setUp(self):
        self.handler = BaseHandler(api_key="test", model_name="test")

    def test_extract_code(self):
        text = "Here is some code:\n```python\nprint('Hello')\n```"
        code = self.handler.extract_code(text)
        self.assertEqual(code, "print('Hello')")

        text_no_code = "Just some text"
        code = self.handler.extract_code(text_no_code)
        self.assertIsNone(code)

    def test_run_code(self):
        code = "x = 10\nprint(x)"
        result = self.handler.run_code(code)
        self.assertIn("10", result)
        self.assertIn("OUTPUT:", result)

    def test_run_code_syntax_error(self):
        code = "print('Unclosed string"
        result = self.handler.run_code(code)
        self.assertIn("ERRORS:", result)
        self.assertIn("SyntaxError", result)

class TestGeminiHandler(unittest.TestCase):
    @patch('agent.gemini.genai.Client')
    def test_send_message(self, mock_client_class):
        mock_chat = MagicMock()
        mock_chat.send_message.return_value.text = "Response"

        mock_client = MagicMock()
        mock_client.chats.create.return_value = mock_chat
        mock_client_class.return_value = mock_client

        # gemini-2.0-flash is not a thinking model -> standard chat mode
        handler = GeminiHandler(api_key="test")
        response = handler.send_message("Hello")

        self.assertEqual(response, "Response")
        mock_chat.send_message.assert_called_with("Hello")

class TestOpenAIHandler(unittest.TestCase):
    def test_init(self):
        if OpenAIHandler is None:
            self.skipTest("OpenAI not installed")
        
        with patch('agent.openai.OpenAI') as mock_openai:
            handler = OpenAIHandler(api_key="test")
            self.assertIsNotNone(handler.client)

    def test_send_message(self):
        if OpenAIHandler is None:
            self.skipTest("OpenAI not installed")

        with patch('agent.openai.OpenAI') as mock_openai:
            mock_client = MagicMock()
            mock_openai.return_value = mock_client
            
            mock_response = MagicMock()
            mock_response.choices[0].message.content = "GPT Response"
            mock_client.chat.completions.create.return_value = mock_response

            handler = OpenAIHandler(api_key="test")
            response = handler.send_message("Hello")
            
            self.assertEqual(response, "GPT Response")
            self.assertEqual(len(handler.history), 2) # User + Assistant
            self.assertEqual(handler.history[0]['role'], 'user')
            self.assertEqual(handler.history[1]['role'], 'assistant')

if __name__ == '__main__':
    unittest.main()
