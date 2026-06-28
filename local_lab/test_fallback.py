import asyncio
import logging
import os
import time

# Configure logging to see the AIEngine warnings
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("test_fallback")

from sentinel.brain.ai_engine import AIEngine

async def test_fallback():
    logger.info("Starting AIEngine Fallback Test...")
    
    # 1. Break the GROQ API key in the environment so it fails instantly (HTTP 401)
    original_groq = os.environ.get("GROQ_API_KEY", "")
    os.environ["GROQ_API_KEY"] = "gsk_invalid_key_for_testing"
    
    engine = AIEngine()
    
    try:
        logger.info("Attempting a call with force_provider='groq' (but with a broken key).")
        logger.info("We expect it to fail Groq, log a warning, and fallback to the next provider in the chain.")
        
        start_time = time.time()
        
        # We use a very simple prompt to test the connection
        response = await engine.call(
            task_type="parse_message",
            prompt="Reply with the exact word 'FALLBACK_SUCCESS'.",
            temperature=0.0,
            max_tokens=20,
            force_provider="groq"
        )
        
        latency = time.time() - start_time
        logger.info(f"\n✅ Fallback Succeeded!")
        logger.info(f"Final Provider Used: {engine.last_provider_used}")
        logger.info(f"Response: {response}")
        logger.info(f"Total Time: {latency:.2f}s")
        
    except Exception as e:
        logger.error(f"Fallback test failed entirely: {e}")
    finally:
        # Restore the original key
        if original_groq:
            os.environ["GROQ_API_KEY"] = original_groq
        else:
            del os.environ["GROQ_API_KEY"]
            
        await engine.close()

if __name__ == "__main__":
    asyncio.run(test_fallback())
