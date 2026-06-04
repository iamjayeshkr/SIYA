"""
src/vani/core/multimodal.py — Abstract Interfaces and Protocols for Multimodal Expansion
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional


class ImageAnalyzer(ABC):
    """Protocol for image processing, layout analysis, and optical character recognition."""

    @abstractmethod
    def ocr(self, file_path: str) -> str:
        """Extract plain text from an image file (PNG/JPG)."""
        pass

    @abstractmethod
    def describe_scene(self, file_path: str) -> str:
        """Generate a natural language description of image objects and scene layout."""
        pass


class DocumentExtractor(ABC):
    """Protocol for parsing PDF documents, presentation decks, and spreadsheet structures."""

    @abstractmethod
    def extract_text(self, file_path: str) -> str:
        """Extract text chunks from all pages of the document."""
        pass

    @abstractmethod
    def extract_tables(self, file_path: str) -> List[Dict[str, Any]]:
        """Identify and extract tabular data arrays with metadata."""
        pass


class AudioVideoProcessor(ABC):
    """Protocol for processing speech alignment and keyframe visual summaries."""

    @abstractmethod
    def transcribe(self, file_path: str) -> str:
        """Transcribe speech audio contents to text."""
        pass

    @abstractmethod
    def extract_keyframes(self, file_path: str) -> List[str]:
        """Extract list of key frame file paths representing visual changes in video."""
        pass


# ── Mock Implementations for testing & fallback ──────────────────────────────

class MockImageAnalyzer(ImageAnalyzer):
    def ocr(self, file_path: str) -> str:
        return f"[Mock OCR output for {file_path}]: Clean text extracted."

    def describe_scene(self, file_path: str) -> str:
        return f"[Mock Scene Description for {file_path}]: A developer workspace layout."


class MockDocumentExtractor(DocumentExtractor):
    def extract_text(self, file_path: str) -> str:
        return f"[Mock PDF Text output for {file_path}]: Introduction and architectural diagrams."

    def extract_tables(self, file_path: str) -> List[Dict[str, Any]]:
        return [{"table_index": 0, "headers": ["Option", "Score"], "rows": [["Safe", "10"]]}]


class MockAudioVideoProcessor(AudioVideoProcessor):
    def transcribe(self, file_path: str) -> str:
        return f"[Mock Audio Transcript for {file_path}]: Core action items assigned."

    def extract_keyframes(self, file_path: str) -> List[str]:
        return ["/mock/frame1.png", "/mock/frame2.png"]


class MultimodalOrchestrator:
    """Unified interface router for multimodal analysis."""

    def __init__(self) -> None:
        self.image_analyzer: ImageAnalyzer = MockImageAnalyzer()
        self.document_extractor: DocumentExtractor = MockDocumentExtractor()
        self.av_processor: AudioVideoProcessor = MockAudioVideoProcessor()

    def process_file(self, file_path: str, action: str = "summary") -> str:
        """Identify file extension and route to appropriate mock processor."""
        ext = file_path.split(".")[-1].lower()
        
        if ext in ("png", "jpg", "jpeg"):
            if action == "ocr":
                return self.image_analyzer.ocr(file_path)
            return self.image_analyzer.describe_scene(file_path)
            
        elif ext in ("pdf", "docx", "pptx", "xlsx"):
            return self.document_extractor.extract_text(file_path)
            
        elif ext in ("mp3", "wav", "mp4", "avi", "mov"):
            if action == "transcribe" or ext in ("mp3", "wav"):
                return self.av_processor.transcribe(file_path)
            frames = self.av_processor.extract_keyframes(file_path)
            return f"Transcribed video: {self.av_processor.transcribe(file_path)} with {len(frames)} keyframes extracted."
            
        return f"Unknown file format: {ext}. Fallback: read raw text if ascii compatible."
