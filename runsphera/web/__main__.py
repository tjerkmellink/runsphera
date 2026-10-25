"""Launcher: `python -m runsphera.web` starts the local dashboard."""
import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "runsphera.web.app:app",
        host="127.0.0.1",
        port=8000,
        reload=False,
    )
