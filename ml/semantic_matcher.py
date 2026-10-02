from sentence_transformers import SentenceTransformer, util

MODEL_NAME = "all-MiniLM-L6-v2"

model = SentenceTransformer(MODEL_NAME)

def semantic_similarity(name1, name2):
    embedding1 = model.encode(name1, convert_to_tensor=True)
    embedding2 = model.encode(name2, convert_to_tensor=True)

    score = util.cos_sim(embedding1, embedding2)

    return float(score[0][0])

def are_semantically_similar(name1, name2, threshold=0.85):
    score = semantic_similarity(name1, name2)

    return {
        "similarity": score,
        "match": score >= threshold
    }