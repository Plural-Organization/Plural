from plural.relay.rooms import _safe_preview_headers  # pyright: ignore[reportPrivateUsage]


def test_a_preview_cannot_forbid_its_own_frame_on_the_relay() -> None:
    kept = dict(
        _safe_preview_headers(
            [
                ("X-Frame-Options", "DENY"),
                ("Content-Security-Policy", "frame-ancestors 'none'"),
                ("Cross-Origin-Resource-Policy", "same-origin"),
                ("Content-Type", "text/html"),
            ],
            "r_1",
        )
    )
    assert kept == {b"content-type": b"text/html"}
