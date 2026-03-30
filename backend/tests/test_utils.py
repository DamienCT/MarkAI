"""Tests for backend utility functions."""

from app.auth.permissions import ROLES, ROLE_HIERARCHY


class TestRoleConstants:
    """Validate the ROLES and ROLE_HIERARCHY constants."""

    def test_roles_dict_not_empty(self):
        assert len(ROLES) > 0

    def test_role_hierarchy_is_roles(self):
        assert ROLE_HIERARCHY is ROLES

    def test_admin_has_highest_level(self):
        admin_level = ROLES["admin"]
        for role, level in ROLES.items():
            if role != "admin":
                assert admin_level > level, f"admin should outrank {role}"

    def test_viewer_has_lowest_level(self):
        viewer_level = ROLES["viewer"]
        for role, level in ROLES.items():
            if role != "viewer":
                assert viewer_level < level, f"viewer should be below {role}"

    def test_all_levels_are_positive(self):
        for role, level in ROLES.items():
            assert level > 0, f"{role} should have a positive level"
