from curio.screen_capture import compose_screen_label


def test_single_screen_label() -> None:
    label = compose_screen_label(
        screen_index=0, total_screens=1, is_cursor_screen=True
    )
    assert label == "user's screen (cursor is here)"


def test_cursor_screen_label_multi() -> None:
    label = compose_screen_label(
        screen_index=0, total_screens=2, is_cursor_screen=True
    )
    assert label == "screen 1 of 2 — cursor is on this screen (primary focus)"


def test_secondary_screen_label_multi() -> None:
    label = compose_screen_label(
        screen_index=1, total_screens=2, is_cursor_screen=False
    )
    assert label == "screen 2 of 2 — secondary screen"


def test_three_screens_numbering() -> None:
    assert (
        compose_screen_label(
            screen_index=2, total_screens=3, is_cursor_screen=False
        )
        == "screen 3 of 3 — secondary screen"
    )
