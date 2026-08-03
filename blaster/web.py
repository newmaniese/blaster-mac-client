"""
Localhost HTTP UI and JSON API for Blaster Mac Client.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from aiohttp import web

if TYPE_CHECKING:
    from blaster.app import AppController

logger = logging.getLogger("blaster.web")

STATIC_DIR = Path(__file__).resolve().parent / "static"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
CONTROLLER_KEY = web.AppKey("controller", object)


def create_app(controller: AppController) -> web.Application:
    app = web.Application()
    app[CONTROLLER_KEY] = controller

    app.router.add_get("/", handle_index)
    app.router.add_get("/api/status", handle_status)
    app.router.add_post("/api/reconnect", handle_reconnect)
    app.router.add_post("/api/command", handle_command)
    app.router.add_get("/api/config", handle_get_config)
    app.router.add_put("/api/config", handle_put_config)
    app.router.add_get("/api/commands", handle_commands)
    app.router.add_static("/static/", STATIC_DIR, name="static")

    return app


async def start_web(
    controller: AppController,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
) -> web.AppRunner:
    app = create_app(controller)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    logger.info("UI available at http://%s:%s", host, port)
    return runner


def _controller(request: web.Request) -> AppController:
    return request.app[CONTROLLER_KEY]  # type: ignore[return-value]


async def handle_index(_request: web.Request) -> web.FileResponse:
    return web.FileResponse(STATIC_DIR / "index.html")


async def handle_status(request: web.Request) -> web.Response:
    return web.json_response(_controller(request).status())


async def handle_reconnect(request: web.Request) -> web.Response:
    result = await _controller(request).request_reconnect()
    return web.json_response(result)


async def handle_command(request: web.Request) -> web.Response:
    controller = _controller(request)
    try:
        body = await request.json()
    except Exception:
        raise web.HTTPBadRequest(text="JSON body required") from None
    name = body.get("name") if isinstance(body, dict) else None
    if not name or not isinstance(name, str):
        raise web.HTTPBadRequest(text='{"name": "..."} required')
    try:
        result = await controller.send_command(name)
    except RuntimeError as e:
        raise web.HTTPConflict(text=str(e)) from e
    except ValueError as e:
        raise web.HTTPBadRequest(text=str(e)) from e
    except Exception as e:
        logger.exception("Command failed")
        raise web.HTTPInternalServerError(text=str(e)) from e
    return web.json_response(result)


async def handle_get_config(request: web.Request) -> web.Response:
    return web.json_response(_controller(request).config_dict())


async def handle_put_config(request: web.Request) -> web.Response:
    controller = _controller(request)
    try:
        body = await request.json()
    except Exception:
        raise web.HTTPBadRequest(text="JSON body required") from None
    if not isinstance(body, dict):
        raise web.HTTPBadRequest(text="Config must be a JSON object")
    try:
        result = await controller.apply_config(body)
    except ValueError as e:
        raise web.HTTPBadRequest(text=str(e)) from e
    except Exception as e:
        logger.exception("Apply config failed")
        raise web.HTTPInternalServerError(text=str(e)) from e
    return web.json_response(result)


async def handle_commands(request: web.Request) -> web.Response:
    controller = _controller(request)
    try:
        names = await controller.list_commands()
    except Exception as e:
        logger.warning("list_commands failed: %s", e)
        return web.json_response({"commands": [], "error": str(e)})
    return web.json_response({"commands": names})
