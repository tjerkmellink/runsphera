"""Launcher: `python -m running_coach.web` starts the local dashboard."""
import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "running_coach.web.app:app",
        host="127.0.0.1",
        port=8000,
        reload=False,
    )
