from typing import Optional, Dict, Literal
from pydantic import BaseModel, Field
from enum import Enum


class TimeRange(BaseModel):
    start: str  # "HH:MM" 형식
    end: str  # "HH:MM" 형식


class LocationType(str, Enum):
    CAMPUS = "campus"
    OFF_CAMPUS = "off_campus"


class Location(BaseModel):
    type: LocationType  # "campus" 또는 "off_campus"
    building: Optional[str] = None
    map_links: Optional[Dict[str, str]] = None  # 네이버, 카카오 지도 링크
    latitude: Optional[float] = None
    longitude: Optional[float] = None


class Restaurant(BaseModel):
    id: int
    name: str
    type: Literal["student", "vendor", "external"]
    location: Optional[Location] = None
    opening_time: Optional[TimeRange] = None
    break_time: Optional[TimeRange] = None
    breakfast_time: Optional[TimeRange] = None
    brunch_time: Optional[TimeRange] = None
    lunch_time: Optional[TimeRange] = None
    dinner_time: Optional[TimeRange] = None
