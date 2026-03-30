"""Tests for the role-based access control system."""

from app.auth.permissions import ROLES, role_has_access


class TestRoleHasAccess:
    """Verify role_has_access with all defined roles."""

    def test_admin_has_access_to_everything(self):
        for role in ROLES:
            assert role_has_access("admin", role) is True

    def test_manager_has_access_to_manager_and_below(self):
        assert role_has_access("manager", "manager") is True
        assert role_has_access("manager", "editor") is True
        assert role_has_access("manager", "viewer") is True
        assert role_has_access("manager", "admin") is False

    def test_editor_has_access_to_editor_and_below(self):
        assert role_has_access("editor", "editor") is True
        assert role_has_access("editor", "viewer") is True
        assert role_has_access("editor", "admin") is False
        assert role_has_access("editor", "manager") is False

    def test_viewer_only_has_viewer_access(self):
        assert role_has_access("viewer", "viewer") is True
        assert role_has_access("viewer", "editor") is False
        assert role_has_access("viewer", "manager") is False
        assert role_has_access("viewer", "admin") is False

    def test_unknown_user_role_denied(self):
        """An unknown user role should get level 0 and be denied."""
        for role in ROLES:
            assert role_has_access("unknown_role", role) is False

    def test_unknown_required_role_denied(self):
        """An unknown required role should default to level 999."""
        assert role_has_access("admin", "nonexistent") is False

    def test_same_role_always_has_access(self):
        for role in ROLES:
            assert role_has_access(role, role) is True
