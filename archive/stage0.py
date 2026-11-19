import os
from dotenv import load_dotenv
from anthropic import Anthropic

load_dotenv()

client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

response = client.messages.create(
    model="claude-sonnet-5",
    max_tokens=500,
    messages=[
        {"role": "user", "content": "Explain what mitochondria do, in 3 bullet points."}
    ]
)

print(response.content[0].text)