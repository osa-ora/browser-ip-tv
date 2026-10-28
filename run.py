import os
import uvicorn

if __name__ == "__main__":
    host = os.environ.get("LOCAL_IPTV_HOST", "127.0.0.1")
    port = int(os.environ.get("LOCAL_IPTV_PORT", "8766"))
    uvicorn.run("app.main:app", host=host, port=port, reload=False)
