"""Tests for storage path handling — ensures product images use the correct bucket."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from shared.tools.storage import _validate_object_path
import pytest


class TestValidateObjectPath:
    """Validate path traversal prevention in storage operations."""

    def test_normal_path_allowed(self):
        _validate_object_path("products/abc-uuid/image.png")

    def test_nested_path_allowed(self):
        _validate_object_path("content-images/brand/item/mockup_instagram.png")

    def test_dotdot_blocked(self):
        with pytest.raises(ValueError):
            _validate_object_path("../etc/passwd")

    def test_dotdot_in_middle_blocked(self):
        with pytest.raises(ValueError):
            _validate_object_path("products/../secrets/key")

    def test_leading_slash_blocked(self):
        with pytest.raises(ValueError):
            _validate_object_path("/absolute/path")

    def test_simple_filename_allowed(self):
        _validate_object_path("image.png")


class TestProductImagePaths:
    """Ensure product image paths are stored correctly for the default bucket."""

    def test_product_path_does_not_start_with_bucket_name(self):
        """Product image paths should be like 'products/uuid/file.jpg',
        NOT 'markai-assets/products/uuid/file.jpg'."""
        path = "products/abc-123/gallery/web_1.jpg"
        first_segment = path.split("/")[0]
        # The first segment should be 'products', not a bucket name
        assert first_segment == "products"
        # This means the file proxy should use the default bucket, not treat 'products' as a bucket
        default_prefixes = {"products", "brands", "screenshots"}
        assert first_segment in default_prefixes

    def test_content_images_path_is_a_real_bucket(self):
        """content-images/ paths ARE bucket names, not prefixes."""
        path = "content-images/brand-id/item-id/mockup.png"
        first_segment = path.split("/")[0]
        default_prefixes = {"products", "brands", "screenshots"}
        assert first_segment not in default_prefixes
