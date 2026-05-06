import asyncio
import os
import sys
import aiohttp
from loguru import logger

# Add paths to ensure we can import internal modules
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(project_root, "..", "pipecat", "src"))
sys.path.insert(0, os.path.dirname(project_root))
sys.path.insert(0, project_root)

async def warmup():
    logger.info("🚀 Starting Dograh pipeline warmup...")
    
    # 1. Warmup Ollama (Connectivity check)
    try:
        ollama_host = os.getenv("OLLAMA_HOST", "ollama")
        ollama_url = f"http://{ollama_host}:11434"
        logger.info(f"Checking Ollama at {ollama_url}...")
        
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{ollama_url}/api/tags", timeout=5) as resp:
                if resp.status == 200:
                    logger.info("✅ Ollama is reachable.")
                else:
                    logger.warning(f"⚠️ Ollama returned status {resp.status}")
    except Exception as e:
        logger.error(f"❌ Ollama connectivity check failed: {e}")

    # 2. Warmup Pocket TTS (Microservice health check)
    try:
        pocket_tts_url = os.getenv("POCKETTTS_API_URL", "http://pocket-tts:8000")
        logger.info(f"Checking Pocket TTS microservice at {pocket_tts_url}...")
        
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{pocket_tts_url}/health", timeout=10) as resp:
                if resp.status == 200:
                    health = await resp.json()
                    logger.info(f"✅ Pocket TTS microservice is ready: {health}")
                else:
                    logger.warning(f"⚠️ Pocket TTS microservice returned status {resp.status}")
    except Exception as e:
        logger.error(f"❌ Pocket TTS microservice connectivity check failed: {e}")

if __name__ == "__main__":
    # Check if we should skip warmup (e.g. during simple builds)
    if os.getenv("SKIP_WARMUP", "false").lower() == "true":
        logger.info("Skipping warmup as requested.")
        sys.exit(0)
    
    try:
        asyncio.run(warmup())
    except Exception as e:
        logger.error(f"Warmup script encountered an error: {e}")
