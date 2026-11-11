import base64

import pytest

from agno.media import File, Image
from agno.os.routers.agents.sandbox import _uploaded_media

PNG = b"\x89PNG\r\n\x1a\nimage"


def test_json_media_content_is_decoded_from_base64_like_other_routes():
    media = _uploaded_media(
        [{"content": base64.b64encode(PNG).decode(), "format": "png"}],
        [{"content": base64.b64encode(b"notes").decode(), "filename": "notes.txt"}],
    )
    assert [image.content for image in media["images"]] == [PNG]
    assert [(file.filename, file.content) for file in media["files"]] == [("notes.txt", b"notes")]


def test_uploaded_objects_pass_through_unchanged():
    image, file = Image(content=PNG), File(content=b"notes", filename="notes.txt")
    media = _uploaded_media([image], [file])
    assert media["images"] == [image] and media["files"] == [file]


@pytest.mark.parametrize(
    "images, files",
    [
        ([{"filepath": "/etc/hosts"}], []),
        ([], [{"content": base64.b64encode(b"x").decode(), "filepath": "/etc/hosts"}]),
        ([{}], []),
    ],
)
def test_server_paths_and_undecodable_entries_are_refused(images, files):
    with pytest.raises(ValueError):
        _uploaded_media(images, files)
