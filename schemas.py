"""Pydantic schemas for API request/response validation."""

from pydantic import BaseModel, Field, ConfigDict
from typing import Optional


class FighterBase(BaseModel):
    """Base fighter schema with common attributes."""
    name: str = Field(..., description="Fighter's full name")
    url: str = Field(..., description="UFC stats profile URL")
    
    height: Optional[int] = Field(None, description="Height in inches")
    weight: Optional[str] = Field(None, description="Weight with unit")
    weight_class: Optional[str] = Field(None, description="UFC weight division")
    reach: Optional[int] = Field(None, description="Reach in inches")
    stance: Optional[str] = Field(None, description="Fighting stance")
    dob: Optional[str] = Field(None, description="Date of birth")
    
    slpm: Optional[float] = Field(None, description="Significant strikes landed per minute")
    stracc: Optional[float] = Field(None, description="Striking accuracy (0-1)")
    sapm: Optional[float] = Field(None, description="Significant strikes absorbed per minute")
    strdef: Optional[float] = Field(None, description="Strike defense (0-1)")
    tdavg: Optional[float] = Field(None, description="Takedown average per 15min")
    tdacc: Optional[float] = Field(None, description="Takedown accuracy (0-1)")
    tddef: Optional[float] = Field(None, description="Takedown defense (0-1)")
    subavg: Optional[float] = Field(None, description="Submission average per 15min")
    
    record: Optional[str] = Field(None, description="Win-Loss-Draw record")
    most_recent_fight: Optional[int] = Field(None, description="Days since last fight")
    fight_count: Optional[int] = Field(None, description="Total career fights")
    fights_in_ufc: Optional[str] = Field(None, description="Number of UFC fights")
    bad_sample: Optional[bool] = Field(None, description="Data quality flag")


class FighterSchema(FighterBase):
    """Complete fighter schema for API responses."""
    id: int = Field(..., description="Unique database ID")
    
    model_config = ConfigDict(from_attributes=True)


class FighterListResponse(BaseModel):
    """Response schema for listing multiple fighters."""
    count: int = Field(..., description="Total number of fighters returned")
    fighters: list[FighterSchema] = Field(..., description="List of fighter objects")


class FighterDetailResponse(BaseModel):
    """Response for a single fighter detail."""
    fighter: FighterSchema = Field(..., description="Fighter details")


class MessageResponse(BaseModel):
    """Generic message response."""
    message: str = Field(..., description="Status or info message")
    success: bool = Field(..., description="Whether operation succeeded")


class ErrorResponse(BaseModel):
    """Standard error response format."""
    detail: str = Field(..., description="Error message")
    error_code: Optional[str] = Field(None, description="Machine-readable error code")
