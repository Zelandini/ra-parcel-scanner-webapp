import base64
from pathlib import Path
from typing import Literal, Optional

from google import genai
from pydantic import BaseModel, Field, model_validator


MODEL = "gemini-3.5-flash-lite"

PROMPT = """
Read this parcel label and extract the intended recipient's delivery details.

Recipient rules:

- Identify the intended parcel recipient.
- Do not use the sender, retailer, courier, customer-support contact,
  or return-address contact.
- Preserve the recipient's name exactly as printed.
- Do not guess missing characters.

Phone rules:

- Extract a phone number only when it belongs to the recipient or
  delivery contact.
- Preserve the phone number exactly as printed.
- Do not extract courier, retailer, sender, or customer-support numbers.
- Return null if no recipient phone number is clearly visible.

CPSV room rules:

Valid CPSV building numbers are:

831, 832, 833, 834, 835, 836, 837

A valid internal room number has exactly three digits.

A room may optionally have one final letter:

A, B, C or D

The building number and room letter may be missing from the parcel.

Valid examples:

Visible: "831-104A"
building_number: "831"
room_number: "104"
room_letter: "A"
raw_room_text: "831-104A"

Visible: "Room 204C"
building_number: null
room_number: "204"
room_letter: "C"
raw_room_text: "Room 204C"

Visible: "Flat 306"
building_number: null
room_number: "306"
room_letter: null
raw_room_text: "Flat 306"

Visible: "104A"
building_number: null
room_number: "104"
room_letter: "A"
raw_room_text: "104A"

Visible: "104"
building_number: null
room_number: "104"
room_letter: null
raw_room_text: "104"

Invalid room examples:

- "19/26" is not a room.
- "12-14 STREET ADDRESS" is a street address, not a room.
- A date is not a room.
- A postcode is not a room.
- A phone number is not a room.
- A tracking number is not a room.
- A street number is not a room.
- A building number by itself, such as "831", is not a room number.

Only extract a room when:

- it is clearly labelled as Room, Flat, Unit or Apartment; or
- it clearly follows one of the valid room formats above.

If a valid three-digit room cannot be identified:

- room_number must be null
- room_letter must be null
- raw_room_text must be null

Do not infer the CPSV building number from the street address,
residence name, suburb, or room floor.

Other rules:

- Preserve raw_room_text exactly as visible.
- Return null for unclear or missing fields.
- Do not guess.
- Confidence must be high, medium or low.
"""

class ParcelData(BaseModel):
    recipient_full_name: Optional[str] = None
    phone_number: Optional[str] = None

    raw_room_text: Optional[str] = None

    building_number: Optional[
        Literal[
            "831",
            "832",
            "833",
            "834",
            "835",
            "836",
            "837",
        ]
    ] = None

    room_number: Optional[str] = Field(
        default=None,
        pattern=r"^\d{3}$",
        description="Exactly three internal room digits.",
    )

    room_letter: Optional[
        Literal["A", "B", "C", "D"]
    ] = None

    tracking_number: Optional[str] = None

    confidence: Literal[
        "high",
        "medium",
        "low",
    ]

    @model_validator(mode="after")
    def remove_invalid_room_details(self):
        """
        A room letter or raw room value cannot exist without a valid
        three-digit room number.
        """
        if self.room_number is None:
            self.room_letter = None
            self.raw_room_text = None

        return self


def read_parcel(image_path, client=None):
    """Extract structured parcel data from one JPEG image."""
    image_bytes = Path(image_path).read_bytes()
    client = client or genai.Client()
    interaction = client.interactions.create(
        model=MODEL,
        input=[
            {"type": "text", "text": PROMPT},
            {
                "type": "image",
                "data": base64.b64encode(image_bytes).decode("utf-8"),
                "mime_type": "image/jpeg",
            },
        ],
        response_format={
            "type": "text",
            "mime_type": "application/json",
            "schema": ParcelData.model_json_schema(),
        },
    )
    return ParcelData.model_validate_json(interaction.output_text)