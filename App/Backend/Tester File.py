import sys
import os

from App.Backend.Annotation_Functions.Semantic_Score import semantic_search

# Add local folders to path
sys.path.append(os.path.join(os.getcwd(), 'Annotation_Functions'))
sys.path.append(os.path.join(os.getcwd(), 'Visualization_Functions'))

from Annotation_Functions.Embedder import add_embeddings_in_place
from Annotation_Functions.Dimensionality_Reducer import reduce_embeddings_with_umap
from Annotation_Functions.Clustering import cluster_with_hdbscan
from Visualization_Functions.Distance_Map import generate_intertopic_distance_map
from Annotation_Functions.Keyword_Score import keyword_search
from Annotation_Functions.Semantic_Score import semantic_search
from Annotation_Functions.Hybrid_Score import hybrid_search
from Distillation_Functions.Numerical_Filtering import numerical_search

def run_full_pipeline(file_path):
    print("--- Starting Pipeline ---")
    add_embeddings_in_place(file_path, "abstract", "abstract_embedding", 'allenai/specter2_base')
    reduce_embeddings_with_umap(file_path, "abstract_embedding", "5d", n_components=5)
    reduce_embeddings_with_umap(file_path, "abstract_embedding", "2d", n_components=2)
    cluster_with_hdbscan(file_path, "5d", "topic_id", min_cluster_size=32, min_samples=8)
    generate_intertopic_distance_map(file_path, "topic_id", "abstract", "2d")



    
    keyword_search(file_path, query="my query", text_column="abstract", new_column_name="kw")
    semantic_search(file_path, query="my query", embedding_column="abstract_embedding", new_column_name="sem")
    hybrid_search(file_path, keyword_col="kw", semantic_col="sem", new_column_name="hybrid")
    numerical_search(file_path, output_csv="Filtered_Output.csv", target_score_column="hybrid", threshold=0.70)
    print("--- Pipeline Complete ---")

if __name__ == "__main__":
    TARGET_FILE = "App/Backend/CSVs/Space_Biology.csv"
    run_full_pipeline(TARGET_FILE)