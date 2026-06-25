import sys
import os

# Add local folders to path
sys.path.append(os.path.join(os.getcwd(), 'Annotation_Functions'))
sys.path.append(os.path.join(os.getcwd(), 'Visualization_Functions'))

from Annotation_Functions.Embedder import add_embeddings_in_place
from Annotation_Functions.Dimensionality_Reducer import reduce_embeddings_with_umap
from Annotation_Functions.Clustering import cluster_with_hdbscan
from Visualization_Functions.Distance_Map import generate_intertopic_distance_map

def run_full_pipeline(file_path):
    print("--- Starting Pipeline ---")
    add_embeddings_in_place(file_path, "abstract", "abstract_embedding", 'allenai/specter2_base')
    reduce_embeddings_with_umap(file_path, "abstract_embedding", "5d", n_components=5)
    reduce_embeddings_with_umap(file_path, "abstract_embedding", "2d", n_components=2)
    cluster_with_hdbscan(file_path, "5d", "topic_id", min_cluster_size=32, min_samples=8)
    generate_intertopic_distance_map(file_path, "topic_id", "abstract", "2d")
    print("--- Pipeline Complete ---")

if __name__ == "__main__":
    TARGET_FILE = "App/Backend/CSVs/Space_Biology.csv"
    run_full_pipeline(TARGET_FILE)