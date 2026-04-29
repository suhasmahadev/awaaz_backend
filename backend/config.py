import os
from dotenv import load_dotenv

# Load variables from .env file into os.environ
load_dotenv()

# Database
DATABASE_URL = os.getenv("DATABASE_URL")

# Security & Auth
SECRET_KEY = os.getenv("SECRET_KEY", "fallback_secret")
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", 1440))
ANON_SALT = os.getenv("ANON_SALT", "")
ENCLAVE_KEY = os.getenv("ENCLAVE_KEY", "")
TEE_DEMO_MODE = os.getenv("TEE_DEMO_MODE", "true").lower() == "true"

# Google AI
GOOGLE_GENAI_USE_VERTEXAI = os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")

# Near AI
NEAR_AI_KEY = os.getenv("NEAR_AI_KEY", "")
NEAR_AI_MODEL = os.getenv("NEAR_AI_MODEL", "deepseek-ai/DeepSeek-V3.1")
NEAR_AI_BASE = os.getenv("NEAR_AI_BASE", "https://cloud-api.near.ai/v1")

# Frontend
VITE_API_BASE = os.getenv("VITE_API_BASE", "http://localhost:8000")
