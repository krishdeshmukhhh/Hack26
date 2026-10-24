from curio.conversation_history import ConversationHistory, MAX_TURNS


def test_append_and_count() -> None:
    history = ConversationHistory()
    history.append("hi", "hello")
    history.append("what", "thing")
    assert history.turn_count() == 2


def test_caps_at_max_turns() -> None:
    history = ConversationHistory()
    for i in range(MAX_TURNS + 5):
        history.append(f"q{i}", f"a{i}")
    assert history.turn_count() == MAX_TURNS
    # Oldest turns should be dropped, newest kept
    messages = history.messages_for_request(
        current_user_text="current", current_images=[]
    )
    # First prior-turn message should be q5 / a5, not q0
    first_user = messages[0]
    assert first_user["role"] == "user"
    assert first_user["content"] == "q5"


def test_messages_for_request_puts_images_on_current_only() -> None:
    history = ConversationHistory()
    history.append("prev-q", "prev-a")
    fake_image = {"type": "image", "source": {"data": "...", "media_type": "image/jpeg"}}
    messages = history.messages_for_request(
        current_user_text="now", current_images=[fake_image]
    )
    # Prior turn is text-only
    assert messages[0] == {"role": "user", "content": "prev-q"}
    assert messages[1] == {"role": "assistant", "content": "prev-a"}
    # Current turn has images AND text
    current = messages[2]
    assert current["role"] == "user"
    assert isinstance(current["content"], list)
    content_types = [block.get("type") for block in current["content"]]
    assert "image" in content_types
    assert "text" in content_types


def test_empty_history_only_current_turn() -> None:
    history = ConversationHistory()
    messages = history.messages_for_request(
        current_user_text="first question", current_images=[]
    )
    assert len(messages) == 1
    assert messages[0]["role"] == "user"
