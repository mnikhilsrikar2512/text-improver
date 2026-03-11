import unittest
from unittest.mock import Mock, patch

import redis
from fastapi import HTTPException

import app.services.ai_rewriter as ai_rewriter
import app.services.cache_service as cache_service
import app.services.feedback_service as feedback_service
import app.services.fallback_rewriter as fallback_rewriter
import app.services.guardrails as guardrails
import app.services.rate_limiter as rate_limiter
import app.services.system_health as system_health
from app.utils.hash_utils import build_cache_key


class GuardrailTests(unittest.TestCase):

    def test_validate_input_trims_text(self):
        self.assertEqual(guardrails.validate_input("  hello  "), "hello")

    def test_validate_input_rejects_blank_strings(self):
        with self.assertRaises(HTTPException) as context:
            guardrails.validate_input("   ")

        self.assertEqual(context.exception.status_code, 400)
        self.assertEqual(context.exception.detail, "Text is empty")

    def test_validate_input_rejects_long_strings(self):
        with self.assertRaises(HTTPException) as context:
            guardrails.validate_input("a" * 1001)

        self.assertEqual(context.exception.status_code, 400)
        self.assertEqual(context.exception.detail, "Text too long")

    def test_enforce_guardrails_rejects_inappropriate_language(self):
        with self.assertRaises(HTTPException) as context:
            guardrails.enforce_guardrails("That coworker is an idiot")

        self.assertEqual(context.exception.status_code, 400)


class AiRewriterParseTests(unittest.TestCase):

    def setUp(self):
        self.correct_grammar_patcher = patch.object(
            ai_rewriter,
            "correct_grammar",
            side_effect=lambda value: value,
        )
        self.correct_grammar_patcher.start()

    def tearDown(self):
        self.correct_grammar_patcher.stop()

    def test_parse_output_accepts_expected_json(self):
        raw = '{"suggestions":["One","Two","Three"]}'
        self.assertEqual(ai_rewriter.parse_output(raw), ["One", "Two", "Three"])

    def test_parse_output_accepts_nested_response_json(self):
        raw = '{"response":"{\\"suggestions\\":[\\"One\\",\\"Two\\"]}"}'
        self.assertEqual(ai_rewriter.parse_output(raw), ["One", "Two"])

    def test_parse_output_accepts_list_of_rewritten_objects(self):
        raw = '[{"original":"x","rewritten":"Professional rewrite"}]'
        self.assertEqual(ai_rewriter.parse_output(raw), ["Professional rewrite"])

    def test_parse_output_accepts_plain_text_numbered_list(self):
        raw = "Here are three rewritten versions:\\n1. First\\n2. Second\\n3. Third"
        self.assertEqual(ai_rewriter.parse_output(raw), ["First", "Second", "Third"])

    def test_parse_output_ignores_code_fence_lines(self):
        raw = "```\\nProfessional rewrite\\n```"
        self.assertEqual(ai_rewriter.parse_output(raw), [])

    def test_parse_output_accepts_json_inside_code_fences(self):
        raw = "```json\\n{\"suggestions\":[\"One\",\"Two\"]}\\n```"
        self.assertEqual(ai_rewriter.parse_output(raw), ["One", "Two"])

    def test_parse_output_accepts_labeled_rewrite_object(self):
        raw = '{"Rewrite 1":"We appreciate your understanding and support.","Rewrite 2":"Thank you for your support and understanding."}'
        self.assertEqual(
            ai_rewriter.parse_output(raw),
            [
                "We appreciate your understanding and support.",
                "Thank you for your support and understanding.",
            ],
        )

    def test_parse_output_discards_punctuation_only_lines(self):
        raw = '{\\n"Rewrite 1": "We appreciate your understanding and support.",\\n,\\n}'
        self.assertEqual(
            ai_rewriter.parse_output(raw),
            ["We appreciate your understanding and support."],
        )

    def test_generate_suggestions_retries_until_parseable_output(self):
        with patch.object(
            ai_rewriter,
            "call_model",
            side_effect=["not json", '{"suggestions":["One"]}', '{"suggestions":["Two"]}'],
        ) as call_model:
            improved_input, suggestions = ai_rewriter.generate_suggestions("sample")

        self.assertEqual(improved_input, "sample")
        self.assertEqual(suggestions, [])
        self.assertEqual(call_model.call_count, 3)

    def test_generate_suggestions_retries_when_output_is_low_quality(self):
        with patch.object(
            ai_rewriter,
            "call_model",
            side_effect=[
                '{"suggestions":["Short one","Short two"]}',
                '{"suggestions":["We appreciate your understanding and support.","Thank you for your patience and support.","We value your understanding and continued support."]}',
            ],
        ) as call_model:
            improved_input, suggestions = ai_rewriter.generate_suggestions("sample")

        self.assertEqual(improved_input, "sample")
        self.assertEqual(
            suggestions,
            [
                "We appreciate your understanding and support.",
                "Thank you for your patience and support.",
                "We value your understanding and continued support.",
            ],
        )
        self.assertEqual(call_model.call_count, 2)


class FallbackRewriteTests(unittest.TestCase):

    def test_fallback_rewrite_rotates_by_attempt(self):
        with patch.object(fallback_rewriter, "correct_grammar", return_value="Need to reschedule"):
            first_batch = fallback_rewriter.fallback_rewrite("Need to reschedule", attempt=0)
            second_batch = fallback_rewriter.fallback_rewrite("Need to reschedule", attempt=1)

        self.assertNotEqual(first_batch[0], second_batch[0])
        self.assertEqual(len(first_batch), 10)

    def test_fallback_rewrite_varies_by_intent(self):
        with patch.object(
            fallback_rewriter,
            "correct_grammar",
            side_effect=[
                "I am writing to request leave for Monday and Tuesday",
                "Thank you for your understanding and support",
            ],
        ):
            leave_suggestions = fallback_rewriter.fallback_rewrite("leave", attempt=0)
            gratitude_suggestions = fallback_rewriter.fallback_rewrite("thanks", attempt=0)

        self.assertTrue(any("leave" in suggestion.lower() for suggestion in leave_suggestions))
        self.assertTrue(any("thank" in suggestion.lower() or "appreciate" in suggestion.lower() for suggestion in gratitude_suggestions))
        self.assertNotEqual(leave_suggestions[0], gratitude_suggestions[0])

    def test_fallback_rewrite_strips_leading_phrase_for_leave_requests(self):
        with patch.object(
            fallback_rewriter,
            "correct_grammar",
            return_value="I am writing to request leave for Monday and Tuesday",
        ):
            suggestions = fallback_rewriter.fallback_rewrite("leave", attempt=0)

        self.assertEqual(
            suggestions[0],
            "I would like to request leave for Monday and Tuesday.",
        )

    def test_fallback_rewrite_handles_sick_leave_naturally(self):
        with patch.object(
            fallback_rewriter,
            "correct_grammar",
            return_value="I am not feeling good today so I need leave",
        ):
            suggestions = fallback_rewriter.fallback_rewrite("sick leave", attempt=0)

        self.assertEqual(
            suggestions[0],
            "I am not feeling well today, so I would like to take leave.",
        )


class FeedbackServiceTests(unittest.TestCase):

    def test_apply_feedback_learning_filters_rejected_and_promotes_accepted_style(self):
        profile = {
            "accepted_examples": ["I would like to request leave for today."],
            "rejected_examples": ["Please be informed that I need leave today."],
            "accepted_tokens": {"request": 1, "leave": 1, "today": 1},
            "rejected_tokens": {"informed": 1},
            "version": 1,
        }

        suggestions = feedback_service.apply_feedback_learning(
            [
                "Please be informed that I need leave today.",
                "I would like to request leave for today.",
                "I need leave today.",
            ],
            profile,
        )

        self.assertEqual(
            suggestions,
            [
                "I would like to request leave for today.",
                "I need leave today.",
            ],
        )

    def test_record_feedback_updates_examples_and_version(self):
        fake_redis = Mock()
        fake_redis.get.return_value = None

        with patch.object(feedback_service, "redis_client", fake_redis):
            learned = feedback_service.record_feedback(
                "Need leave today",
                accepted_suggestion="I would like to request leave for today.",
                rejected_suggestions=["Please be informed that I need leave today."],
            )

        self.assertEqual(learned["accepted"], 1)
        self.assertEqual(learned["rejected"], 1)
        self.assertEqual(learned["version"], 1)
        fake_redis.setex.assert_called_once()

    def test_build_preference_context_uses_recent_examples(self):
        context = feedback_service.build_preference_context(
            {
                "accepted_examples": ["A", "B"],
                "rejected_examples": ["C"],
                "accepted_tokens": {},
                "rejected_tokens": {},
                "version": 1,
            }
        )

        self.assertIn("Prefer suggestions", context)
        self.assertIn("Avoid suggestions", context)


class RedisBackedServiceTests(unittest.TestCase):

    def test_build_cache_key_includes_versioning_fields(self):
        key = build_cache_key("Need to reschedule")

        self.assertIn("rewrite:", key)
        self.assertIn("batch3", key)
        self.assertIn("pool12", key)

    def test_get_cached_returns_none_when_redis_errors(self):
        broken_redis = Mock()
        broken_redis.get.side_effect = redis.RedisError("down")

        with patch.object(cache_service, "redis_client", broken_redis):
            self.assertIsNone(cache_service.get_cached("key"))

    def test_cache_suggestions_ignores_redis_errors(self):
        broken_redis = Mock()
        broken_redis.setex.side_effect = redis.RedisError("down")

        with patch.object(cache_service, "redis_client", broken_redis):
            cache_service.cache_suggestions("key", {"suggestions": ["value"]})

        broken_redis.setex.assert_called_once()

    def test_cache_payload_compatibility_requires_metadata(self):
        self.assertFalse(cache_service.is_cache_payload_compatible({"suggestion_pool": ["one"]}))
        self.assertTrue(
            cache_service.is_cache_payload_compatible(
                {"suggestion_pool": ["one"], "cache_metadata": {"cache_version": "rewrite_v1"}}
            )
        )

    def test_rate_limiter_allows_request_when_redis_errors(self):
        broken_redis = Mock()
        broken_redis.get.side_effect = redis.RedisError("down")

        with patch.object(rate_limiter, "redis_client", broken_redis):
            rate_limiter.check_rate_limit("127.0.0.1")

    def test_rate_limiter_fails_closed_when_required(self):
        broken_redis = Mock()
        broken_redis.get.side_effect = redis.RedisError("down")

        with patch.object(rate_limiter, "redis_client", broken_redis), \
             patch.object(rate_limiter, "REQUIRE_REDIS", True):
            with self.assertRaises(HTTPException) as context:
                rate_limiter.check_rate_limit("127.0.0.1")

        self.assertEqual(context.exception.status_code, 503)

    def test_rate_limiter_blocks_when_limit_is_reached(self):
        redis_client = Mock()
        redis_client.get.return_value = str(rate_limiter.RATE_LIMIT)

        with patch.object(rate_limiter, "redis_client", redis_client):
            with self.assertRaises(HTTPException) as context:
                rate_limiter.check_rate_limit("127.0.0.1")

        self.assertEqual(context.exception.status_code, 429)
        self.assertEqual(context.exception.detail, "Rate limit exceeded")


class SystemHealthTests(unittest.TestCase):

    def test_readiness_is_ready_when_redis_ok(self):
        with patch.object(system_health, "ping_redis", return_value=True):
            readiness = system_health.readiness_status()

        self.assertTrue(readiness["ready"])
        self.assertEqual(readiness["components"]["redis"], "ok")

    def test_readiness_is_not_ready_when_redis_required_and_down(self):
        with patch.object(system_health, "ping_redis", return_value=False), \
             patch.object(system_health, "REQUIRE_REDIS", True):
            readiness = system_health.readiness_status()

        self.assertFalse(readiness["ready"])
        self.assertEqual(readiness["components"]["redis"], "unavailable")
