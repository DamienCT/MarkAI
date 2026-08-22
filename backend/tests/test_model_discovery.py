"""Tests for the AI model discovery service — response schema and categorization."""

from app.services.ai_model_service import _categorize_model
from app.schemas.ai_model import DiscoverModelsResponse


class TestCategorizeModel:
    """Validate model ID categorization logic."""

    def test_gpt4_is_text(self):
        cats = _categorize_model("gpt-4o")
        assert "text" in cats

    def test_gpt4_mini_is_text_fast_primary(self):
        cats = _categorize_model("gpt-4o-mini")
        assert cats[0] == "text-fast"

    def test_dalle_is_image(self):
        cats = _categorize_model("dall-e-3")
        assert "image" in cats

    def test_embedding_model(self):
        cats = _categorize_model("text-embedding-3-small")
        assert "embedding" in cats

    def test_whisper_is_stt(self):
        cats = _categorize_model("whisper-1")
        assert "stt" in cats

    def test_tts_model(self):
        cats = _categorize_model("tts-1-hd")
        assert "tts" in cats

    def test_unknown_model_returns_empty(self):
        cats = _categorize_model("some-random-model-name")
        assert cats == []

    def test_o1_is_text(self):
        cats = _categorize_model("o1-preview")
        assert "text" in cats

    def test_chat_models_get_vision(self):
        cats = _categorize_model("gpt-4o")
        assert "vision" in cats

    def test_gpt_image_is_image(self):
        cats = _categorize_model("gpt-image-1")
        assert "image" in cats

    def test_veo_is_video(self):
        cats = _categorize_model("veo-3.1-fast-generate-preview")
        assert "video" in cats

    def test_sora_is_never_a_video_model(self):
        # Locked decision: never Sora (OpenAI Videos API dies 2026-09-24).
        # A sora-* id showing up in a provider catalog must not be
        # classified as a usable video model.
        assert _categorize_model("sora-2-pro") == []


class TestDiscoverModelsResponse:
    """Validate the response schema includes diagnostic fields."""

    def test_schema_includes_totals(self):
        resp = DiscoverModelsResponse(
            discovered=5,
            updated=3,
            unavailable=1,
            total_from_api=150,
            total_in_db=148,
        )
        assert resp.total_from_api == 150
        assert resp.total_in_db == 148

    def test_defaults_to_zero(self):
        resp = DiscoverModelsResponse(discovered=0, updated=0, unavailable=0)
        assert resp.total_from_api == 0
        assert resp.total_in_db == 0
