import base64

from agno.media import Audio, File, Image, Video
from agno.run.agent import RunInput, RunOutput
from agno.utils.media import (
    reconstruct_audio_from_dict,
    reconstruct_audio_list,
    reconstruct_file_from_dict,
    reconstruct_files,
    reconstruct_image_from_dict,
    reconstruct_images,
    reconstruct_response_audio,
    reconstruct_video_from_dict,
    reconstruct_videos,
)


def test_reconstruct_image_from_base64():
    """Test that images with base64 content are properly reconstructed."""
    # Create an image with binary content
    original_content = b"fake image data"
    base64_content = base64.b64encode(original_content).decode("utf-8")

    img_data = {
        "id": "test-img-1",
        "content": base64_content,
        "mime_type": "image/png",
        "format": "png",
        "detail": "high",
    }

    reconstructed = reconstruct_image_from_dict(img_data)

    assert isinstance(reconstructed, Image)
    assert reconstructed.id == "test-img-1"
    assert reconstructed.content == original_content
    assert reconstructed.mime_type == "image/png"


def test_reconstruct_image_from_url():
    """Test that images with URL are properly reconstructed."""
    img_data = {
        "id": "test-img-2",
        "url": "https://example.com/image.png",
        "mime_type": "image/png",
    }

    reconstructed = reconstruct_image_from_dict(img_data)

    assert isinstance(reconstructed, Image)
    assert reconstructed.id == "test-img-2"
    assert reconstructed.url == "https://example.com/image.png"


def test_reconstruct_video_from_base64():
    """Test that videos with base64 content are properly reconstructed."""
    original_content = b"fake video data"
    base64_content = base64.b64encode(original_content).decode("utf-8")

    vid_data = {
        "id": "test-vid-1",
        "content": base64_content,
        "mime_type": "video/mp4",
        "format": "mp4",
    }

    reconstructed = reconstruct_video_from_dict(vid_data)

    assert isinstance(reconstructed, Video)
    assert reconstructed.id == "test-vid-1"
    assert reconstructed.content == original_content
    assert reconstructed.mime_type == "video/mp4"


def test_reconstruct_video_from_filepath():
    """Test that videos with filepath are properly reconstructed."""
    vid_data = {
        "id": "test-vid-2",
        "filepath": "/path/to/video.mp4",
        "mime_type": "video/mp4",
    }

    reconstructed = reconstruct_video_from_dict(vid_data)

    assert isinstance(reconstructed, Video)
    assert reconstructed.id == "test-vid-2"
    assert reconstructed.filepath == "/path/to/video.mp4"


def test_reconstruct_audio_from_base64():
    """Test that audio with base64 content is properly reconstructed."""
    original_content = b"fake audio data"
    base64_content = base64.b64encode(original_content).decode("utf-8")

    aud_data = {
        "id": "test-aud-1",
        "content": base64_content,
        "mime_type": "audio/mp3",
        "transcript": "Hello world",
        "sample_rate": 24000,
        "channels": 1,
    }

    reconstructed = reconstruct_audio_from_dict(aud_data)

    assert isinstance(reconstructed, Audio)
    assert reconstructed.id == "test-aud-1"
    assert reconstructed.content == original_content
    assert reconstructed.transcript == "Hello world"


def test_reconstruct_audio_from_url():
    """Test that audio with URL is properly reconstructed."""
    aud_data = {
        "id": "test-aud-2",
        "url": "https://example.com/audio.mp3",
        "mime_type": "audio/mp3",
    }

    reconstructed = reconstruct_audio_from_dict(aud_data)

    assert isinstance(reconstructed, Audio)
    assert reconstructed.id == "test-aud-2"
    assert reconstructed.url == "https://example.com/audio.mp3"


def test_reconstruct_file_from_base64():
    """Test that files with base64 content are properly reconstructed."""
    original_content = b"fake file data"
    base64_content = base64.b64encode(original_content).decode("utf-8")

    file_data = {
        "id": "test-file-1",
        "content": base64_content,
        "mime_type": "application/pdf",
        "filename": "test.pdf",
        "name": "Test Document",
    }

    reconstructed = reconstruct_file_from_dict(file_data)

    assert isinstance(reconstructed, File)
    assert reconstructed.id == "test-file-1"
    assert reconstructed.content == original_content
    assert reconstructed.filename == "test.pdf"
    assert reconstructed.name == "Test Document"


def test_reconstruct_file_from_filepath():
    """Test that files with filepath are properly reconstructed."""
    file_data = {
        "id": "test-file-2",
        "filepath": "/path/to/document.pdf",
        "mime_type": "application/pdf",
    }

    reconstructed = reconstruct_file_from_dict(file_data)

    assert isinstance(reconstructed, File)
    assert reconstructed.id == "test-file-2"
    assert reconstructed.filepath == "/path/to/document.pdf"


def test_reconstruct_images_list():
    """Test reconstruction of multiple images."""
    original_content_1 = b"fake image 1"
    original_content_2 = b"fake image 2"

    images_data = [
        {
            "id": "img-1",
            "content": base64.b64encode(original_content_1).decode("utf-8"),
            "mime_type": "image/png",
        },
        {
            "id": "img-2",
            "content": base64.b64encode(original_content_2).decode("utf-8"),
            "mime_type": "image/jpeg",
        },
    ]

    reconstructed_list = reconstruct_images(images_data)

    assert len(reconstructed_list) == 2
    assert all(isinstance(img, Image) for img in reconstructed_list)
    assert reconstructed_list[0].content == original_content_1
    assert reconstructed_list[1].content == original_content_2


def test_reconstruct_videos_list():
    """Test reconstruction of multiple videos."""
    videos_data = [
        {"id": "vid-1", "url": "https://example.com/video1.mp4"},
        {"id": "vid-2", "filepath": "/path/to/video2.mp4"},
    ]

    reconstructed_list = reconstruct_videos(videos_data)

    assert len(reconstructed_list) == 2
    assert all(isinstance(vid, Video) for vid in reconstructed_list)


def test_reconstruct_audio_list():
    """Test reconstruction of multiple audio files."""
    audio_data = [
        {"id": "aud-1", "url": "https://example.com/audio1.mp3"},
        {"id": "aud-2", "filepath": "/path/to/audio2.mp3"},
    ]

    reconstructed_list = reconstruct_audio_list(audio_data)

    assert len(reconstructed_list) == 2
    assert all(isinstance(aud, Audio) for aud in reconstructed_list)


def test_reconstruct_files_list():
    """Test reconstruction of multiple files."""
    files_data = [
        {"id": "file-1", "url": "https://example.com/doc1.pdf"},
        {"id": "file-2", "filepath": "/path/to/doc2.pdf"},
    ]

    reconstructed_list = reconstruct_files(files_data)

    assert len(reconstructed_list) == 2
    assert all(isinstance(f, File) for f in reconstructed_list)


def test_reconstruct_response_audio():
    """Test reconstruction of single response audio."""
    original_content = b"response audio data"
    base64_content = base64.b64encode(original_content).decode("utf-8")

    audio_data = {
        "id": "response-aud",
        "content": base64_content,
        "mime_type": "audio/wav",
    }

    reconstructed = reconstruct_response_audio(audio_data)

    assert isinstance(reconstructed, Audio)
    assert reconstructed.content == original_content


def test_reconstruct_none_values():
    """Test that None values are handled properly."""
    assert reconstruct_images(None) is None
    assert reconstruct_videos(None) is None
    assert reconstruct_audio_list(None) is None
    assert reconstruct_files(None) is None
    assert reconstruct_response_audio(None) is None


def test_reconstruct_empty_lists():
    """Test that empty lists return None."""
    assert reconstruct_images([]) is None
    assert reconstruct_videos([]) is None
    assert reconstruct_audio_list([]) is None
    assert reconstruct_files([]) is None


def test_run_input_from_dict_with_base64_images():
    """Test RunInput.from_dict properly reconstructs images with base64 content."""
    original_content = b"test image content"
    base64_content = base64.b64encode(original_content).decode("utf-8")

    data = {
        "input_content": "Test message",
        "images": [
            {
                "id": "img-1",
                "content": base64_content,
                "mime_type": "image/png",
            }
        ],
    }

    run_input = RunInput.from_dict(data)

    assert run_input.images is not None
    assert len(run_input.images) == 1
    assert isinstance(run_input.images[0], Image)
    assert run_input.images[0].content == original_content
    assert run_input.images[0].id == "img-1"


def test_run_input_from_dict_with_multiple_media_types():
    """Test RunInput.from_dict with images, videos, audio, and files."""
    img_content = b"image data"
    vid_content = b"video data"
    aud_content = b"audio data"
    file_content = b"file data"

    data = {
        "input_content": "Test with all media types",
        "images": [
            {
                "id": "img-1",
                "content": base64.b64encode(img_content).decode("utf-8"),
                "mime_type": "image/png",
            }
        ],
        "videos": [
            {
                "id": "vid-1",
                "content": base64.b64encode(vid_content).decode("utf-8"),
                "mime_type": "video/mp4",
            }
        ],
        "audios": [
            {
                "id": "aud-1",
                "content": base64.b64encode(aud_content).decode("utf-8"),
                "mime_type": "audio/mp3",
            }
        ],
        "files": [
            {
                "id": "file-1",
                "content": base64.b64encode(file_content).decode("utf-8"),
                "mime_type": "application/pdf",
            }
        ],
    }

    run_input = RunInput.from_dict(data)

    assert run_input.images[0].content == img_content
    assert run_input.videos[0].content == vid_content
    assert run_input.audios[0].content == aud_content
    assert run_input.files[0].content == file_content


def test_run_output_from_dict_with_base64_media():
    """Test RunOutput.from_dict properly reconstructs media with base64 content."""
    img_content = b"output image"
    audio_content = b"output audio"

    data = {
        "content": "Test output",
        "images": [
            {
                "id": "out-img-1",
                "content": base64.b64encode(img_content).decode("utf-8"),
                "mime_type": "image/png",
            }
        ],
        "response_audio": {
            "id": "resp-aud",
            "content": base64.b64encode(audio_content).decode("utf-8"),
            "mime_type": "audio/wav",
        },
    }

    run_output = RunOutput.from_dict(data)

    assert run_output.images is not None
    assert len(run_output.images) == 1
    assert run_output.images[0].content == img_content
    assert run_output.response_audio is not None
    assert run_output.response_audio.content == audio_content


def test_session_persistence_simulation():
    """
    Simulate the session persistence bug scenario:
    1. Create RunInput with image
    2. Serialize to dict (simulating database storage)
    3. Deserialize from dict (simulating retrieval)
    4. Verify image content is intact
    """
    # First run - create input with image
    original_content = b"original image from first run"
    image1 = Image(content=original_content, mime_type="image/png")
    run_input_1 = RunInput(input_content="First run", images=[image1])

    # Simulate storage: convert to dict (base64 encoding happens here)
    stored_dict_1 = run_input_1.to_dict()

    # Verify base64 encoding happened
    assert isinstance(stored_dict_1["images"][0]["content"], str)

    # Second run - retrieve first run's data
    retrieved_input_1 = RunInput.from_dict(stored_dict_1)

    assert retrieved_input_1.images[0].content == original_content
    assert isinstance(retrieved_input_1.images[0].content, bytes)

    # Add second image
    second_content = b"second image from second run"
    image2 = Image(content=second_content, mime_type="image/jpeg")
    run_input_2 = RunInput(input_content="Second run", images=[image2])

    stored_dict_2 = run_input_2.to_dict()
    retrieved_input_2 = RunInput.from_dict(stored_dict_2)

    # Both images should have valid content
    assert retrieved_input_1.images[0].content == original_content
    assert retrieved_input_2.images[0].content == second_content
