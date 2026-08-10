from capability_exchange import adaptation


def test_m4_public_surface_exports_preview_and_single_use_approval() -> None:
    assert adaptation.AdaptationPreview.__name__ == "AdaptationPreview"
    assert adaptation.ApprovalAuthority.__name__ == "ApprovalAuthority"
    assert callable(adaptation.build_preview)
