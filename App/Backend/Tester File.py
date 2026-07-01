import sys
import os

current_dir = os.path.dirname(os.path.abspath(__file__))
target_path = os.path.abspath(os.path.join(current_dir, ".."))
if target_path not in sys.path:
    sys.path.append(target_path)

from Backend.Annotation_Functions.Embed_Text import embed_text
from Backend.Annotation_Functions.Reduce_Dimensionality import reduce_dimensionality
from Backend.Annotation_Functions.Cluster import cluster
from Backend.Visualization_Functions.Distance_Map import distance_map
from Backend.Annotation_Functions.Keyword_Score import keyword_score
from Backend.Annotation_Functions.Semantic_Score import semantic_score
from Backend.Annotation_Functions.Hybrid_Score import hybrid_score
from Backend.Distillation_Functions.Numerical_Filter import numerical_filter

def run_full_pipeline(csv_name):
    print("--- Starting Pipeline ---")
    #embed_text(csv_name, "abstract", "abstract_embedding", 'allenai/specter2_base')
    reduce_dimensionality(csv_name, "abstract_embedding", "5d", n_components=5)
    reduce_dimensionality(csv_name, "abstract_embedding", "2d", n_components=2)
    cluster(csv_name, "5d", "topic_id", min_cluster_size=32, min_samples=8)
    distance_map(csv_name, "topic_id", "abstract", "2d")

    keyword_score(csv_name, query="microgravity", text_column="abstract", new_column_name="kw")
    semantic_score(csv_name, query="miccrogravity", embedding_column="abstract_embedding", new_column_name="sem")
    hybrid_score(csv_name, keyword_col="kw", semantic_col="sem", new_column_name="hybrid")
    numerical_filter(csv_name, output_csv="Filtered_Output", target_score_column="hybrid", threshold=0.70)
    print("--- Pipeline Complete ---")

if __name__ == "__main__":
    TARGET_NAME = "Space_Biology"
    run_full_pipeline(TARGET_NAME)