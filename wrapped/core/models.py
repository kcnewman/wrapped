from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class Scrobble(BaseModel):
    """A completed listening event"""

    model_config = ConfigDict(
        strict=True, frozen=True, extra="forbid", hide_input_in_errors=True
    )

    username: Text
    uts: Annotated[int, Field(ge=0)]
    artist: Text
    track: Text
    album: Text | None = None
    artist_mbid: Text | None = None
    track_mbid: Text | None = None
