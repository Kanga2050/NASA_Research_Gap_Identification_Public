import fitz 
import numpy as np
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity


class PDFSemanticSegmenter:
    def __init__(
        self,
        embedding_model="all-MiniLM-L6-v2",
        similarity_threshold=0.65,
    ):
        self.model = SentenceTransformer(embedding_model)
        self.similarity_threshold = similarity_threshold

    def extract_text(self, pdf_path):
        doc = fitz.open(pdf_path)

        pages = []
        for page in doc:
            pages.append(page.get_text())

        return "\n".join(pages)

    def paragraph_split(self, text):
        paragraphs = [
            p.strip()
            for p in text.split("\n\n")
            if len(p.strip()) > 50
        ]
        return paragraphs

    def compute_embeddings(self, paragraphs):
        return self.model.encode(
            paragraphs,
            convert_to_numpy=True,
            normalize_embeddings=True
        )

    def segment(self, paragraphs):
        if len(paragraphs) <= 1:
            return [{"section_id": 0, "content": paragraphs}]

        embeddings = self.compute_embeddings(paragraphs)

        sections = []
        current_section = [paragraphs[0]]

        for i in range(1, len(paragraphs)):
            sim = cosine_similarity(
                embeddings[i - 1].reshape(1, -1),
                embeddings[i].reshape(1, -1)
            )[0][0]

            if sim < self.similarity_threshold:
                sections.append(current_section)
                current_section = [paragraphs[i]]
            else:
                current_section.append(paragraphs[i])

        sections.append(current_section)

        return [
            {
                "section_id": idx,
                "content": section
            }
            for idx, section in enumerate(sections)
        ]

    def process_pdf(self, pdf_path):
        text = self.extract_text(pdf_path)
        paragraphs = self.paragraph_split(text)
        sections = self.segment(paragraphs)

        return {
            "paragraph_count": len(paragraphs),
            "section_count": len(sections),
            "sections": sections
        }


if __name__ == "__main__":
    segmenter = PDFSemanticSegmenter(
        similarity_threshold=0.60
    )

    result = segmenter.process_pdf("document.pdf")

    print(f"Sections found: {result['section_count']}")

    for section in result["sections"]:
        print(f"\n=== SECTION {section['section_id']} ===\n")
        print("\n\n".join(section["content"][:3]))