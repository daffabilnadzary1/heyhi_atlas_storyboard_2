"""Simple script: send an image to GPT and print a description."""

import base64
import mimetypes
import os
import sys

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
client = OpenAI(api_key=os.environ["HEYHI_OPENAI_API_KEY"])


def describe(image_path: str) -> str:
    mime = mimetypes.guess_type(image_path)[0] or "image/jpeg"
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Describe this image in 65 words."},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{b64}"},
                    },
                ],
            }
        ],
    )
    return response.choices[0].message.content


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "image.jpg"
    print(describe(path))
