"""
Monkey-patches pocket-tts's /health endpoint to return 503 
until the model is confirmed loaded.
"""
import logging
from fastapi.responses import JSONResponse
from pocket_tts.main import web_app

logger = logging.getLogger("pocket-tts-health")

@web_app.get("/health", include_in_schema=False)
def health_check():
    """
    Overridden health endpoint that checks if tts_model is initialized.
    """
    try:
        import pocket_tts.main as ptts_main
        model = getattr(ptts_main, "tts_model", None)
        if model is None:
            return JSONResponse(
                status_code=503,
                content={"status": "unavailable", "reason": "model not loaded"}
            )
        return JSONResponse(
            status_code=200,
            content={"status": "ok", "sample_rate": 24000}
        )
    except Exception as e:
        logger.error(f"Health check error: {e}")
        return JSONResponse(
            status_code=503,
            content={"status": "error", "reason": str(e)}
        )
