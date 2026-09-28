"""Keep repeated model statistics honest about failures and Safety bypasses."""

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from check_decision import evaluate, percentile  # noqa: E402
from check_decision_resources import summarize  # noqa: E402
from open_llm_vtuber.mental_health.schemas import DecisionResult  # noqa: E402


class DecisionCheckTests(unittest.IsolatedAsyncioTestCase):
    async def test_three_rounds_count_success_and_timeout_separately(self):
        good = DecisionResult()
        good.trace.source = "model"
        good.trace.latency_ms = 10
        primary = SimpleNamespace(
            decide=AsyncMock(side_effect=[asyncio.TimeoutError()] + [good] * 17)
        )
        report = await evaluate(primary, repeats=3)
        self.assertEqual(primary.decide.await_count, 18)
        self.assertEqual(report["model_success_count"], 17)
        self.assertEqual(report["fallback_count"], 1)
        self.assertAlmostEqual(report["valid_rate"], 17 / 18)
        self.assertFalse(report["engineering_target_met"])
        risk = [r for r in report["cases"] if r["source"] == "safety_gate"]
        self.assertEqual(len(risk), 3)
        self.assertEqual(sum(r["requests"] for r in risk), 0)
        self.assertEqual(report["model_success_latency_ms"]["p95"], 10)

    async def test_rules_are_not_model_success_and_invalid_repeat_is_rejected(self):
        report = await evaluate(repeats=3)
        self.assertEqual(report["model_requests"], 0)
        self.assertEqual(report["model_success_count"], 0)
        self.assertIsNone(report["valid_rate"])
        self.assertIsNone(report["engineering_target_met"])
        self.assertIsNone(report["latency_ms"]["p95"])
        for repeats in (0, 101):
            with self.assertRaises(ValueError):
                await evaluate(repeats=repeats)

    def test_nearest_rank_percentile_includes_tail_failures(self):
        self.assertEqual(percentile([1] * 17 + [15000], 0.95), 15000)
        self.assertEqual(percentile([9, 1, 5], 0.5), 5)
        self.assertIsNone(percentile([], 0.95))

    def test_resource_failure_is_unknown_and_devices_not_summed(self):
        missing = {"memory": {"available": False}, "gpu": {"available": False}}
        result = summarize([missing])
        self.assertIsNone(result["system_ram_used_peak_bytes"])
        self.assertEqual(result["gpu_used_peak_mib"], {})
        result = summarize(
            [
                missing,
                {
                    "memory": {"available": True, "used_bytes": 123},
                    "gpu": {
                        "devices": [
                            {"index": 0, "used_mib": 10},
                            {"index": 1, "used_mib": 20},
                        ]
                    },
                },
            ]
        )
        self.assertEqual(result["gpu_used_peak_mib"], {"0": 10, "1": 20})
