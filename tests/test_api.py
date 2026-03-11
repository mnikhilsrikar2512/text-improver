import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

import app.api.routes as routes
from app.config import CACHE_VERSION, MODEL_NAME, PROMPT_VERSION, SUGGESTION_POOL_SIZE


class ImproveTextRouteTests(unittest.TestCase):

    def setUp(self):
        self.request = SimpleNamespace(
            client=SimpleNamespace(host="127.0.0.1"),
            state=SimpleNamespace(request_id="req-123"),
        )

    def test_health_returns_ok_status(self):
        self.assertEqual(routes.health(), {"status": "ok"})

    def test_ready_returns_ready_status(self):
        with patch.object(routes, "readiness_status", return_value={"ready": True, "components": {"redis": "ok"}}):
            self.assertEqual(routes.ready(), {"status": "ready", "components": {"redis": "ok"}})

    def test_ready_raises_when_dependency_unavailable(self):
        with patch.object(routes, "readiness_status", return_value={"ready": False, "components": {"redis": "unavailable"}}):
            with self.assertRaises(HTTPException) as context:
                routes.ready()

        self.assertEqual(context.exception.status_code, 503)

    def test_improve_text_returns_cached_response(self):
        request_model = SimpleNamespace(text="  please review the draft  ", attempt=1)
        cached_payload = {
            "improved_input": "please review the draft",
            "suggestion_pool": [
                "cached suggestion one",
                "cached suggestion two",
                "cached suggestion three",
                "cached suggestion four",
                "cached suggestion five",
                "cached suggestion six",
            ],
            "cache_metadata": {
                "cache_version": CACHE_VERSION,
                "model_name": MODEL_NAME,
                "prompt_version": PROMPT_VERSION,
                "pool_size": SUGGESTION_POOL_SIZE,
                "feedback_version": 0,
            },
        }

        with patch.object(routes, "check_rate_limit") as check_rate_limit, \
             patch.object(routes, "get_feedback_profile", return_value={"version": 0, "accepted_examples": [], "rejected_examples": [], "accepted_tokens": {}, "rejected_tokens": {}}), \
             patch.object(routes, "get_cached", return_value=cached_payload) as get_cached, \
             patch.object(routes, "generate_suggestions") as generate_suggestions, \
             patch.object(routes, "fallback_rewrite") as fallback_rewrite, \
             patch.object(routes, "cache_suggestions") as cache_suggestions, \
             patch.object(routes, "log_event") as log_event:
            response = routes.improve_text(request_model, self.request)

        check_rate_limit.assert_called_once_with("127.0.0.1")
        get_cached.assert_called_once()
        generate_suggestions.assert_not_called()
        fallback_rewrite.assert_not_called()
        cache_suggestions.assert_not_called()
        log_event.assert_called_once()
        self.assertEqual(response["original"], "please review the draft")
        self.assertEqual(response["improved_input"], "please review the draft")
        self.assertEqual(
            response["suggestions"],
            [
                "cached suggestion four.",
                "cached suggestion five.",
                "cached suggestion six.",
            ],
        )
        self.assertEqual(response["selected_index"], 0)
        self.assertEqual(response["selected_suggestion"], "cached suggestion four.")
        self.assertEqual(response["attempt_metadata"]["batch_size"], 3)
        self.assertEqual(response["attempt_metadata"]["pool_size"], 6)
        self.assertEqual(response["attempt_metadata"]["batch_start"], 3)
        self.assertEqual(response["attempt_metadata"]["next_attempt"], 2)
        self.assertFalse(response["attempt_metadata"]["wrapped"])
        self.assertTrue(response["cached"])
        self.assertIsInstance(response["latency_ms"], int)
        self.assertEqual(log_event.call_args.kwargs["request_id"], "req-123")

    def test_improve_text_normalizes_cached_object_suggestions(self):
        request_model = SimpleNamespace(text="  leave request  ", attempt=0)
        cached_payload = {
            "improved_input": "leave request",
            "suggestion_pool": [
                {"original": "leave request", "rewritten": "Please approve my leave request."}
            ],
            "cache_metadata": {
                "cache_version": CACHE_VERSION,
                "model_name": MODEL_NAME,
                "prompt_version": PROMPT_VERSION,
                "pool_size": SUGGESTION_POOL_SIZE,
                "feedback_version": 0,
            },
        }

        with patch.object(routes, "check_rate_limit"), \
             patch.object(routes, "get_feedback_profile", return_value={"version": 0, "accepted_examples": [], "rejected_examples": [], "accepted_tokens": {}, "rejected_tokens": {}}), \
             patch.object(routes, "get_cached", return_value=cached_payload), \
             patch.object(routes, "generate_suggestions") as generate_suggestions, \
             patch.object(routes, "fallback_rewrite") as fallback_rewrite, \
             patch.object(routes, "cache_suggestions") as cache_suggestions, \
             patch.object(routes, "log_event"):
            response = routes.improve_text(request_model, self.request)

        generate_suggestions.assert_not_called()
        fallback_rewrite.assert_not_called()
        cache_suggestions.assert_not_called()
        self.assertEqual(response["suggestions"], ["Please approve my leave request."])
        self.assertEqual(response["selected_suggestion"], "Please approve my leave request.")
        self.assertEqual(response["attempt_metadata"]["batch_size"], 1)
        self.assertEqual(response["attempt_metadata"]["pool_size"], 1)

    def test_improve_text_uses_model_output_and_caches_payload(self):
        request_model = SimpleNamespace(text="Need to reschedule", attempt=2)

        with patch.object(routes, "check_rate_limit"), \
             patch.object(routes, "get_feedback_profile", return_value={"version": 0, "accepted_examples": [], "rejected_examples": [], "accepted_tokens": {}, "rejected_tokens": {}}), \
             patch.object(routes, "get_cached", return_value=None), \
             patch.object(routes, "generate_suggestions", return_value=("Need to reschedule", ["one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve"])) as generate_suggestions, \
             patch.object(routes, "fallback_rewrite") as fallback_rewrite, \
             patch.object(routes, "cache_suggestions") as cache_suggestions, \
             patch.object(routes, "log_event"):
            response = routes.improve_text(request_model, self.request)

        generate_suggestions.assert_called_once_with(
            "Need to reschedule",
            2,
            feedback_profile={"version": 0, "accepted_examples": [], "rejected_examples": [], "accepted_tokens": {}, "rejected_tokens": {}},
        )
        fallback_rewrite.assert_not_called()
        cache_suggestions.assert_called_once()
        self.assertEqual(response["selected_index"], 0)
        self.assertEqual(response["selected_suggestion"], "seven.")
        self.assertEqual(response["suggestions"], ["seven.", "eight.", "nine."])
        self.assertEqual(response["attempt_metadata"]["batch_start"], 6)
        self.assertFalse(response["attempt_metadata"]["wrapped"])
        self.assertFalse(response["cached"])

    def test_improve_text_ignores_legacy_cache_payload_without_metadata(self):
        request_model = SimpleNamespace(text="Need to reschedule", attempt=0)
        legacy_payload = {
            "improved_input": "stale improved input",
            "suggestion_pool": ["old one", "old two"],
        }

        with patch.object(routes, "check_rate_limit"), \
             patch.object(routes, "get_feedback_profile", return_value={"version": 0, "accepted_examples": [], "rejected_examples": [], "accepted_tokens": {}, "rejected_tokens": {}}), \
             patch.object(routes, "get_cached", return_value=legacy_payload), \
             patch.object(routes, "generate_suggestions", return_value=("Need to reschedule", ["fresh one", "fresh two", "fresh three"])) as generate_suggestions, \
             patch.object(routes, "fallback_rewrite") as fallback_rewrite, \
             patch.object(routes, "cache_suggestions") as cache_suggestions, \
             patch.object(routes, "log_event"):
            response = routes.improve_text(request_model, self.request)

        generate_suggestions.assert_called_once_with(
            "Need to reschedule",
            0,
            feedback_profile={"version": 0, "accepted_examples": [], "rejected_examples": [], "accepted_tokens": {}, "rejected_tokens": {}},
        )
        fallback_rewrite.assert_not_called()
        cache_suggestions.assert_called_once()
        self.assertEqual(response["suggestions"], ["fresh one.", "fresh two.", "fresh three."])
        self.assertFalse(response["cached"])

    def test_improve_text_rotates_fallback_pool_by_attempt(self):
        request_model = SimpleNamespace(text="Need to reschedule", attempt=3)

        with patch.object(routes, "check_rate_limit"), \
             patch.object(routes, "get_feedback_profile", return_value={"version": 0, "accepted_examples": [], "rejected_examples": [], "accepted_tokens": {}, "rejected_tokens": {}}), \
             patch.object(routes, "get_cached", return_value=None), \
             patch.object(routes, "generate_suggestions", return_value=("Need to reschedule", [])), \
             patch.object(routes, "fallback_rewrite", return_value=["one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve"]) as fallback_rewrite, \
             patch.object(routes, "cache_suggestions"), \
             patch.object(routes, "log_event"):
            response = routes.improve_text(request_model, self.request)

        fallback_rewrite.assert_called_once_with("Need to reschedule", 3)
        self.assertEqual(response["suggestions"], ["ten.", "eleven.", "twelve."])
        self.assertEqual(response["selected_suggestion"], "ten.")
        self.assertEqual(response["attempt_metadata"]["batch_start"], 9)
        self.assertFalse(response["attempt_metadata"]["wrapped"])

    def test_improve_text_uses_fallback_when_model_returns_nothing(self):
        request_model = SimpleNamespace(text="Need to reschedule", attempt=1)

        with patch.object(routes, "check_rate_limit"), \
             patch.object(routes, "get_feedback_profile", return_value={"version": 0, "accepted_examples": [], "rejected_examples": [], "accepted_tokens": {}, "rejected_tokens": {}}), \
             patch.object(routes, "get_cached", return_value=None), \
             patch.object(routes, "generate_suggestions", return_value=("Need to reschedule", [])), \
             patch.object(routes, "fallback_rewrite", return_value=["fallback one", "fallback two"]) as fallback_rewrite, \
             patch.object(routes, "cache_suggestions") as cache_suggestions, \
             patch.object(routes, "log_event"):
            response = routes.improve_text(request_model, self.request)

        fallback_rewrite.assert_called_once_with("Need to reschedule", 1)
        cache_suggestions.assert_called_once()
        self.assertEqual(response["suggestions"], ["fallback one.", "fallback two."])
        self.assertEqual(response["selected_suggestion"], "fallback one.")
        self.assertEqual(response["attempt_metadata"]["batch_size"], 2)
        self.assertEqual(response["attempt_metadata"]["pool_size"], 2)
        self.assertFalse(response["cached"])

    def test_improve_text_regenerates_when_feedback_version_changes(self):
        request_model = SimpleNamespace(text="Need to reschedule", attempt=0)
        cached_payload = {
            "improved_input": "Need to reschedule",
            "suggestion_pool": ["cached one", "cached two", "cached three"],
            "cache_metadata": {
                "cache_version": CACHE_VERSION,
                "model_name": MODEL_NAME,
                "prompt_version": PROMPT_VERSION,
                "pool_size": SUGGESTION_POOL_SIZE,
                "feedback_version": 0,
            },
        }
        feedback_profile = {
            "version": 2,
            "accepted_examples": ["Please approve my leave request."],
            "rejected_examples": ["cached one."],
            "accepted_tokens": {"approve": 1},
            "rejected_tokens": {"cached": 1},
        }

        with patch.object(routes, "check_rate_limit"), \
             patch.object(routes, "get_feedback_profile", return_value=feedback_profile), \
             patch.object(routes, "get_cached", return_value=cached_payload), \
             patch.object(routes, "generate_suggestions", return_value=("Need to reschedule", ["fresh one", "fresh two", "fresh three"])) as generate_suggestions, \
             patch.object(routes, "fallback_rewrite") as fallback_rewrite, \
             patch.object(routes, "cache_suggestions") as cache_suggestions, \
             patch.object(routes, "log_event"):
            response = routes.improve_text(request_model, self.request)

        generate_suggestions.assert_called_once()
        fallback_rewrite.assert_not_called()
        cache_suggestions.assert_called_once()
        self.assertFalse(response["cached"])
        self.assertEqual(response["suggestions"], ["fresh one.", "fresh two.", "fresh three."])

    def test_feedback_endpoint_records_accept_and_reject(self):
        request_model = SimpleNamespace(
            text="Need to reschedule",
            accepted_suggestion="I would like to reschedule the meeting.",
            rejected_suggestions=["Please be informed that I need to reschedule."],
        )

        with patch.object(routes, "record_feedback", return_value={"accepted": 1, "rejected": 1, "version": 1}) as record_feedback:
            response = routes.submit_feedback(request_model)

        record_feedback.assert_called_once_with(
            "Need to reschedule",
            accepted_suggestion="I would like to reschedule the meeting.",
            rejected_suggestions=["Please be informed that I need to reschedule."],
        )
        self.assertEqual(response["status"], "recorded")
        self.assertEqual(response["learned_preferences"]["version"], 1)

    def test_improve_text_rejects_blank_input(self):
        request_model = SimpleNamespace(text="   ", attempt=0)

        with patch.object(routes, "check_rate_limit"), \
             patch.object(routes, "get_cached", return_value=None), \
             patch.object(routes, "get_feedback_profile", return_value={"version": 0, "accepted_examples": [], "rejected_examples": [], "accepted_tokens": {}, "rejected_tokens": {}}), \
             patch.object(routes, "generate_suggestions", return_value=("unused", [])), \
             patch.object(routes, "fallback_rewrite", return_value=["unused"]), \
             patch.object(routes, "cache_suggestions"), \
             patch.object(routes, "log_event"):
            with self.assertRaises(HTTPException) as context:
                routes.improve_text(request_model, self.request)

        self.assertEqual(context.exception.status_code, 400)
        self.assertEqual(context.exception.detail, "Text is empty")

    def test_improve_text_rejects_blocked_language(self):
        request_model = SimpleNamespace(text="This manager is an idiot", attempt=0)

        with patch.object(routes, "check_rate_limit"), \
             patch.object(routes, "get_cached", return_value=None), \
             patch.object(routes, "get_feedback_profile", return_value={"version": 0, "accepted_examples": [], "rejected_examples": [], "accepted_tokens": {}, "rejected_tokens": {}}), \
             patch.object(routes, "generate_suggestions", return_value=("unused", [])), \
             patch.object(routes, "fallback_rewrite", return_value=["unused"]), \
             patch.object(routes, "cache_suggestions"), \
             patch.object(routes, "log_event"):
            with self.assertRaises(HTTPException) as context:
                routes.improve_text(request_model, self.request)

        self.assertEqual(context.exception.status_code, 400)
        self.assertIn("cannot be processed", context.exception.detail)
