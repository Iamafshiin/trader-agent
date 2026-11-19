from importlib import resources

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse

from trader_agent.dashboard.data import Reader, now_ms
from trader_agent.settings import load_settings
from trader_agent.strategy.tcp_vp import load_params

RESOLUTIONS = ("15", "60", "D")
HOST = "127.0.0.1"


def create_app(reader: Reader) -> FastAPI:
    app = FastAPI(title="trader-agent dashboard", docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        page = resources.files("trader_agent.dashboard").joinpath("static/index.html")
        return page.read_text("utf-8")

    @app.get("/api/overview")
    def overview() -> dict[str, object]:
        return reader.overview(now_ms())

    @app.get("/api/streams")
    def streams() -> dict[str, object]:
        return reader.streams(now_ms())

    @app.get("/api/candles")
    def candles(
        symbol: str, resolution: str = "15", limit: int = Query(300, ge=1, le=1000)
    ) -> dict[str, object]:
        if symbol not in reader.symbols():
            raise HTTPException(404, "unknown symbol")
        if resolution not in RESOLUTIONS:
            raise HTTPException(404, "unknown resolution")
        return reader.candles(symbol, resolution, limit)

    @app.get("/api/paper")
    def paper(run_id: str | None = None) -> dict[str, object]:
        return reader.paper(run_id)

    @app.get("/api/decisions")
    def decisions(
        run_id: str | None = None, limit: int = Query(50, ge=1, le=200)
    ) -> dict[str, object]:
        return reader.decisions(run_id, limit)

    return app


def serve(port: int) -> None:
    settings = load_settings()
    start = settings.burnin_start
    reader = Reader(
        settings.trader_data_dir,
        load_params(),
        None if start is None else int(start.timestamp() * 1000),
    )
    uvicorn.run(create_app(reader), host=HOST, port=port, log_level="warning", access_log=False)
