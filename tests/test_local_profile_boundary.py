import unittest

from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route, WebSocketRoute
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from open_llm_vtuber.local_profile_boundary import LocalProfileBoundaryMiddleware


class LocalProfileBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.hits = 0

        async def http_endpoint(request):
            self.hits += 1
            return PlainTextResponse("local synthetic content")

        async def websocket_endpoint(websocket):
            self.hits += 1
            await websocket.accept()
            await websocket.send_text("accepted")
            await websocket.close()

        app = Starlette(
            routes=[
                Route("/", http_endpoint),
                WebSocketRoute("/client-ws", websocket_endpoint),
            ]
        )
        self.client = TestClient(
            LocalProfileBoundaryMiddleware(app, port=12393),
            base_url="http://localhost:12393",
        )
        self.addCleanup(self.client.close)

    def test_local_origins_and_non_browser_tools_still_work(self):
        for origin in (
            None,
            "http://localhost:12393",
            "http://127.0.0.1:12393",
            "http://[::1]:12393",
        ):
            with self.subTest(origin=origin):
                headers = {"origin": origin} if origin else {}
                self.assertEqual(self.client.get("/", headers=headers).status_code, 200)
                with self.client.websocket_connect(
                    "ws://localhost:12393/client-ws", headers=headers
                ) as websocket:
                    self.assertEqual(websocket.receive_text(), "accepted")

    def test_remote_null_deceptive_and_wrong_port_origins_never_reach_routes(self):
        for origin in (
            "https://example.com",
            "null",
            "http://localhost.example.com:12393",
            "http://localhost:5173",
            "http://localhost:12393/",
            "http://localhost:12393@evil.test",
        ):
            with self.subTest(origin=origin):
                self.assertEqual(
                    self.client.get("/", headers={"origin": origin}).status_code, 403
                )
                with self.assertRaises(WebSocketDisconnect):
                    with self.client.websocket_connect(
                        "ws://localhost:12393/client-ws", headers={"origin": origin}
                    ):
                        self.fail("Untrusted WebSocket was accepted")
        self.assertEqual(self.hits, 0)

    def test_rebinding_host_and_originless_cross_site_subresource_are_blocked(self):
        for headers in (
            {"host": "attacker.test:12393"},
            {"host": "localhost:8000"},
            {"sec-fetch-site": "cross-site"},
            [("origin", "http://localhost:12393"), ("origin", "https://evil.test")],
        ):
            self.assertEqual(self.client.get("/", headers=headers).status_code, 403)
        self.assertEqual(self.hits, 0)


if __name__ == "__main__":
    unittest.main()
