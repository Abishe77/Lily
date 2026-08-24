from pypdf import PdfReader

reader = PdfReader("Lily_SRS.pdf")
print("Number of pages:", len(reader.pages))

for i in range(len(reader.pages)):
    text = reader.pages[i].extract_text()
    print(f"--- Page {i} ---")
    print(text[:2000] if text else "(no extractable text)")