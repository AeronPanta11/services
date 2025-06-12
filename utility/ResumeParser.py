import os
import spacy

class ResumeParser:
    def __init__(self):
        # Go up one directory from utility, then into model/output80/model-last
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.model_path = os.path.join(base_dir, "model", "output80", "model-last")
        print(f"Loading model from {self.model_path}")

        if not os.path.exists(self.model_path):
            raise FileNotFoundError(
                f"Model not found at {self.model_path}. Check the path and try again.")

        self.nlp = self.load_model()

    def load_model(self):
        return spacy.load(self.model_path)

    def parse_resume(self, text):
        doc = self.nlp(text)
        return {
            "parsed_text": text,
            "entities": [(ent.text, ent.label_) for ent in doc.ents]
        }