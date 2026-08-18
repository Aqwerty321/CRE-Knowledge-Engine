from __future__ import annotations

import uvicorn


if __name__ == "__main__":
    uvicorn.run("gmail_demo.app:app", host="0.0.0.0", port=8030, reload=False)
