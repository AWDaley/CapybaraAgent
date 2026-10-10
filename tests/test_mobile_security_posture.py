from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_android_manifest_remains_local_only_and_non_exporting() -> None:
    manifest = (ROOT / "mobile" / "app" / "src" / "main" / "AndroidManifest.xml").read_text(encoding="utf-8")
    assert "android.permission.INTERNET" not in manifest
    assert 'android:allowBackup="false"' in manifest
    assert 'android:fullBackupContent="false"' in manifest


def test_mobile_tool_catalog_does_not_enable_cloud_model_for_mvp() -> None:
    catalog = (ROOT / "contracts" / "mobile-profile" / "catalog.json").read_text(encoding="utf-8")
    cloud_entry = '"tool_id": "cloud_model.request"'
    assert cloud_entry in catalog
    assert '"tool_id": "cloud_model.request",\n      "version": "1.0.0",\n      "effect": "network",\n      "risk_tier": 3,\n      "mvp_enabled": false' in catalog
