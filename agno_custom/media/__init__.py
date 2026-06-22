"""Media compatibility layer for V1→V2 migration.

V1 had: AudioArtifact, ImageArtifact, VideoArtifact
V2 has: Audio, Image, Video (simpler naming)

This module provides V1-compatible class names that map to V2 equivalents.
"""

from agno.media import Audio, File, Image, Video

# V1 Artifact Classes → V2 Equivalents
AudioArtifact = Audio
ImageArtifact = Image
VideoArtifact = Video
FileArtifact = File

__all__ = ["AudioArtifact", "ImageArtifact", "VideoArtifact", "FileArtifact", "Audio", "Image", "Video", "File"]
