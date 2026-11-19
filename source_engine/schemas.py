from typing import Any, Optional
from pydantic import BaseModel, Field


class BoundingBox(BaseModel):
    x: float
    y: float
    width: float
    height: float


class TextQuality(BaseModel):
    score: Optional[float] = None
    level: Optional[str] = None


class ExtractionBlock(BaseModel):
    block_id: str
    type: str
    text: str
    bbox: Optional[BoundingBox] = None


class Extraction(BaseModel):
    method: str
    text: str
    text_quality: Optional[TextQuality] = None
    blocks: list[ExtractionBlock] = Field(default_factory=list)


class VisualElement(BaseModel):
    element_id: str
    type: str
    text: Optional[str] = None
    source_block_ids: list[str] = Field(default_factory=list)
    bbox: Optional[BoundingBox] = None


class Relationship(BaseModel):
    from_element: str
    to_element: str
    type: str
    direction: Optional[str] = None


class VisualAnalysis(BaseModel):
    visual_type: str
    summary: Optional[str] = None
    elements: list[VisualElement] = Field(default_factory=list)
    relationships: list[Relationship] = Field(default_factory=list)


class Visual(BaseModel):
    present: bool = False
    meaningful: bool = False
    analysis_required: bool = False
    analysis_method: Optional[str] = None
    analysis: Optional[VisualAnalysis] = None


class Completion(BaseModel):
    state: str
    reason: Optional[str] = None


class PageDimensions(BaseModel):
    width: Optional[float] = None
    height: Optional[float] = None
    unit: Optional[str] = None


class SourcePage(BaseModel):
    page_number: int
    status: str
    dimensions: Optional[PageDimensions] = None
    extraction: Optional[Extraction] = None
    visual: Visual = Field(default_factory=Visual)
    completion: Optional[Completion] = None
    error: Optional[dict[str, Any]] = None


class SourceInfo(BaseModel):
    source_id: Optional[int] = None
    filename: str
    file_type: str
    mime_type: str
    total_pages: Optional[int] = None


class ProcessingInfo(BaseModel):
    status: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    processor_version: str = "1.0"


class SourceDocument(BaseModel):
    source: SourceInfo
    processing: ProcessingInfo
    pages: list[SourcePage] = Field(default_factory=list)