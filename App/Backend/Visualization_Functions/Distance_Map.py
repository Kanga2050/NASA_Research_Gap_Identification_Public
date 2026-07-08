import pandas as pd
import numpy as np
import ast
import plotly.express as px
import spacy
from collections import Counter
from pathlib import Path

from Servers.storage_paths import resolve_csv_root, resolve_html_root

try:
    nlp = spacy.load("en_core_web_sm", disable=["parser", "ner"])
    HAS_POS_TAGS = True
except OSError:
    nlp = spacy.blank("en")
    HAS_POS_TAGS = False


def get_topic_names(df, topic_column, text_column, top_n=3):
    topic_names = {}
    for topic_id in df[topic_column].unique():
        if topic_id == -1: continue
        
        topic_texts = " ".join(df[df[topic_column] == topic_id][text_column].fillna("").tolist())
        
        doc = nlp(topic_texts[:100000]) # Limit length for performance
        if HAS_POS_TAGS:
            words = [
                (token.lemma_ or token.text).lower() for token in doc
                if token.is_alpha and not token.is_stop and token.pos_ in ["NOUN", "ADJ"]
            ]
        else:
            words = [
                (token.lemma_ or token.text).lower() for token in doc
                if token.is_alpha and not token.is_stop
            ]
        
        common = Counter(words).most_common(top_n)
        topic_names[topic_id] = ", ".join([word for word, count in common])
        
    return topic_names

def distance_map(
    csv_name: str,
    topic_column: str,
    text_column: str = "abstract",
    coord_column: str = "2d",
    output_name: str = "Space_Biology_Topics",
    title: str = "",
    csv_root: str | Path | None = None,
    html_root: str | Path | None = None,
):
    csv_path = resolve_csv_root(csv_root) / f"{csv_name}.csv"
    output_html = resolve_html_root(html_root) / f"{output_name}.html"
    print(f"Loading data from '{csv_path}'...")
    df = pd.read_csv(csv_path)
    
    valid_rows = df[coord_column].dropna().index
    parsed_coords = df.loc[valid_rows, coord_column].apply(ast.literal_eval)
    df['x'] = np.nan
    df['y'] = np.nan
    df.loc[valid_rows, 'x'] = [coord[0] for coord in parsed_coords]
    df.loc[valid_rows, 'y'] = [coord[1] for coord in parsed_coords]

    topics_df = df[df[topic_column] != -1]
    topic_stats = topics_df.groupby(topic_column).agg(
        x=('x', 'mean'), y=('y', 'mean'), size=('x', 'count')
    ).reset_index()

    print("Generating keyword labels for topics...")
    labels = get_topic_names(topics_df, topic_column, text_column)
    topic_stats['Topic_Label'] = topic_stats[topic_column].map(labels)

    fig = px.scatter(
        topic_stats, x='x', y='y', size='size',
        color='Topic_Label', hover_name='Topic_Label',
        title=title or 'Intertopic Distance Map',
        size_max=60
    )

    fig.update_traces(marker=dict(sizemode='area', sizemin=5, opacity=0.8, line=dict(width=1, color='Black')))
    fig.update_layout(xaxis=dict(visible=False), yaxis=dict(visible=False), plot_bgcolor='white')

    fig.write_html(output_html)
    print(f"Success! Map saved to {output_html}")

if __name__ == "__main__":

    TARGET_NAME = "Space_Biology"
    distance_map(
        csv_name=TARGET_NAME,
        topic_column="topic_id",
        text_column="abstract",
        coord_column="2d",
        output_name="Space_Biology_Topics"
    )