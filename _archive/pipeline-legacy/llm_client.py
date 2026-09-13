"""
Local LLM Client for Ollama/LM Studio

This client connects to a local LLM server (Ollama or LM Studio)
and supports JSON output validation via Pydantic.
"""
import os
import json
import time
import requests
from typing import Optional, Dict, Any
from pydantic import BaseModel, field_validator
from urllib.parse import urljoin


class LLMClient:
    """Client for local LLMs (Ollama or LM Studio)

    Supports:
    - JSON output validation
    - Retry logic
    - Error fallbacks
    - Custom prompts
    - Timeout handling
    """

    def __init__(self, base_url: str = None, model: str = "llama3.2:3b", max_retries: int = 3, timeout: int = 30):
        """
        Args:
            base_url: e.g., "http://localhost:11434" (Ollama) or "http://localhost:1865" (LM Studio)
            model: LLM model name
            max_retries: number of retry attempts on failure
            timeout: request timeout in seconds
        """
        self.base_url = base_url or os.getenv("LLM_BASE_URL", "http://localhost:11434")
        self.model = model
        self.max_retries = max_retries
        self.timeout = timeout
        self.session = requests.Session()

        # Ensure base URL ends with slash
        if not self.base_url.endswith('/'):
            self.base_url += '/'

        # Test connection
        self._test_connection()

    def _test_connection(self) -> bool:
        """Test if the LLM server is reachable"""
        try:
            url = urljoin(self.base_url, "api/tags")
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            return True
        except requests.RequestException as e:
            print(f"[LLM Client] Connection failed: {e}")
            raise

    def generate_json(self, prompt: str, schema: type[BaseModel] = None, temperature: float = 0.3) -> Optional[Dict[Any, Any]]:
        """
        Generate JSON output from LLM with optional schema validation

        Args:
            prompt: The input prompt
            schema: Optional Pydantic model for validation
            temperature: LLM randomness (0.0–1.0)

        Returns:
            Parsed JSON dict or None on failure
        """
        if not prompt:
            raise ValueError("Prompt must not be empty")

        # Construct the request
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "temperature": temperature,
            "max_tokens": 3000,
            "format": "json"
        }

        # Add schema instruction if provided
        if schema:
            schema_str = self._get_schema_instruction(schema)
            payload["prompt"] = f"{prompt}\n\n{schema_str}"

        # Retry logic
        for attempt in range(self.max_retries):
            try:
                url = urljoin(self.base_url, "api/generate")
                response = self.session.post(
                    url,
                    json=payload,
                    timeout=self.timeout
                )

                if response.status_code != 200:
                    error_msg = f"LLM Error: {response.status_code} - {response.text}"
                    print(error_msg)
                    raise Exception(error_msg)

                data = response.json()
                content = data.get("response", "")

                # Clean up response (remove markdown, extra quotes, etc.)
                content = content.strip()
                if content.startswith("```"):
                    content = content[3:]
                if content.endswith("```"):
                    content = content[:-3]
                if content.startswith("\"") and content.endswith("\""):
                    content = content[1:-1]

                # Parse JSON
                try:
                    # Handle edge case: if response is malformed JSON
                    if not content or content == "{}" or content == "" or content == "null":
                        return None

                    # Parse the result
                    result = json.loads(content)

                    # Validate against schema if provided
                    if schema:
                        validated = schema.model_validate(result)
                        return validated.model_dump()

                    return result

                except json.JSONDecodeError as e:
                    print(f"[JSON Parse Error] Attempt {attempt + 1}: {e}\nRaw: {content}")
                    if attempt == self.max_retries - 1:
                        raise
                    time.sleep(1)

            except Exception as e:
                print(f"[Request Failed] Attempt {attempt + 1}: {e}")
                if attempt == self.max_retries - 1:
                    raise
                time.sleep(2 ** (attempt + 1))  # Exponential backoff

        return None

    def _get_schema_instruction(self, schema: type[BaseModel]) -> str:
        """Generate a clear instruction to guide the LLM to produce valid schema output."""
        instructions = [
            "Return only JSON that matches the following schema.",
            "Do not include any explanations, extra text, or markdown.",
            "Ensure all required fields are present."
        ]
        return "\n".join(instructions)

    def get_models(self) -> list:
        """List available models on the server."""
        try:
            url = urljoin(self.base_url, "api/tags")
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            data = response.json()
            return [model["name"] for model in data.get("models", [])]
        except Exception as e:
            print(f"[Get Models] Failed: {e}")
            return []


# === EXAMPLE USAGE ===
if __name__ == "__main__":
    # Test with a simple schema
    class TestSchema(BaseModel):
        title: str
        author: str
        year: int

        @field_validator("year")
        @classmethod
        def validate_year(cls, v: int) -> int:
            if v < 1900 or v > 2030:
                raise ValueError("Year must be between 1900 and 2030")
            return v

    # Initialize client
    client = LLMClient(model="llama3.2:3b")

    # Test prompt
    prompt = "Create a book with the title 'The Sky That Never Opens', author 'Akira Tanaka', published in 2022."
    result = client.generate_json(prompt, TestSchema)

    if result:
        print("✅ Success!")
        print(json.dumps(result, indent=2))
    else:
        print("❌ Failed to generate valid JSON")

    # List available models
    models = client.get_models()
    print(f"Available models: {models}")
