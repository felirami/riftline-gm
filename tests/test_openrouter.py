from riftline_gm.openrouter import _content_to_text, _first_image_url


def test_content_to_text_accepts_string_and_parts():
    assert _content_to_text("hello") == "hello"
    assert _content_to_text([{"type": "text", "text": "hello"}, {"type": "text", "text": "world"}]) == "hello\nworld"


def test_first_image_url_accepts_openrouter_shapes():
    message = {"images": [{"image_url": {"url": "data:image/png;base64,abc"}}]}
    assert _first_image_url(message) == "data:image/png;base64,abc"

    camel = {"images": [{"imageUrl": {"url": "https://example.com/a.png"}}]}
    assert _first_image_url(camel) == "https://example.com/a.png"

