from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm

from .models import AgentSettings


class SignupForm(UserCreationForm):
    class Meta:
        model = get_user_model()
        fields = ("username",)


class UsernameForm(forms.ModelForm):
    class Meta:
        model = get_user_model()
        fields = ("username",)


class AgentSettingsForm(forms.ModelForm):
    class Meta:
        model = AgentSettings
        fields = ("gemini_api_key", "model")
        labels = {"gemini_api_key": "Gemini API key", "model": "Model"}
        widgets = {
            "gemini_api_key": forms.PasswordInput(
                render_value=True, attrs={"placeholder": "AIza…", "autocomplete": "off"}
            ),
        }


class ApiKeyCreateForm(forms.Form):
    name = forms.CharField(max_length=100, label="Key name")


class TaskSubmitForm(forms.Form):
    AGG_CHOICES = [("count", "count"), ("mean", "mean"), ("sum", "sum"), ("min", "min"), ("max", "max")]
    UNIT_CHOICES = [("words", "words"), ("chars", "chars")]
    OPERATION_CHOICES = [("add", "add"), ("subtract", "subtract"), ("multiply", "multiply"), ("divide", "divide")]

    ACTION_CHOICES = [
        ("embed_text", "Embed text"),
        ("reduce_dimensionality", "Reduce dimensionality"),
        ("cluster", "Cluster"),
        ("keyword_score", "Keyword score"),
        ("semantic_score", "Semantic score"),
        ("hybrid_score", "Hybrid score"),
        ("word_frequency", "Word frequency (per row)"),
        ("label_topics", "Label topics"),
        ("text_length", "Text length"),
        ("extract_year", "Extract year"),
        ("to_date", "To date (ISO-8601)"),
        ("normalize_column", "Normalize column"),
        ("hierarchical_cluster", "Hierarchical cluster"),
        ("numerical_filter", "Numerical filter"),
        ("categorical_filter", "Categorical filter"),
        ("top_n_by_column", "Top N by column"),
        ("deduplicate", "Deduplicate"),
        ("select_columns", "Select columns"),
        ("group_aggregate", "Group aggregate"),
        ("aggregate_dictionary", "Aggregate dictionary"),
        ("cross_tab", "Cross tab"),
        ("arithmetic", "Arithmetic"),
        ("combine_csvs", "Combine CSVs"),
        ("bar_chart", "Bar chart"),
        ("scatter_plot", "Scatter plot"),
        ("histogram", "Histogram"),
        ("line_chart", "Line chart"),
        ("box_plot", "Box plot"),
        ("heatmap", "Heatmap"),
        ("pie_chart", "Pie chart"),
        ("distance_map", "Distance map"),
        ("hierarchical_dendrogram", "Hierarchical dendrogram"),
        ("openalex_scraper", "OpenAlex scrape"),
        ("chunk_pdfs", "Chunk PDFs"),
    ]

    action = forms.ChoiceField(choices=ACTION_CHOICES)
    csv_name = forms.CharField(max_length=120, required=False)
    source_csv = forms.CharField(max_length=120, required=False)
    source_csvs = forms.CharField(max_length=500, required=False)
    output_csv = forms.CharField(max_length=120, required=False)
    query = forms.CharField(max_length=300, required=False)
    topic = forms.CharField(max_length=300, required=False)
    text_column = forms.CharField(max_length=120, required=False, initial="text")
    embedding_column = forms.CharField(max_length=120, required=False, initial="text_embedding")
    output_column = forms.CharField(max_length=120, required=False)
    output_name = forms.CharField(max_length=120, required=False)
    topic_column = forms.CharField(max_length=120, required=False, initial="topic_id")
    keyword_col = forms.CharField(max_length=120, required=False, initial="kw")
    semantic_col = forms.CharField(max_length=120, required=False, initial="sem")
    target_score_column = forms.CharField(max_length=120, required=False, initial="hybrid")
    model_name = forms.CharField(max_length=200, required=False, initial="allenai/specter2_base")
    n_components = forms.IntegerField(required=False, initial=2)
    min_cluster_size = forms.IntegerField(required=False, initial=32)
    min_samples = forms.IntegerField(required=False, initial=8)
    threshold = forms.FloatField(required=False, initial=0.7)
    limit = forms.IntegerField(required=False, initial=10000)
    # Import: chunk_pdfs (comma-separated PDF collection folder names)
    folders = forms.CharField(max_length=1000, required=False)
    source_label = forms.CharField(max_length=120, required=False)
    chunk_words = forms.IntegerField(required=False, initial=250)
    overlap_words = forms.IntegerField(required=False, initial=40)
    # enrich defaults on; unchecking has no effect from the form (a False value is
    # falsy and falls back to the TASK_SPECS default) -- pass enrich=False via MCP/API
    # for a purely offline run.
    enrich = forms.BooleanField(required=False, initial=True)
    # Distillation
    target_column = forms.CharField(max_length=120, required=False)
    expected_value = forms.CharField(max_length=300, required=False)
    source_column = forms.CharField(max_length=120, required=False, initial="source")
    dict_column = forms.CharField(max_length=120, required=False, initial="word_freq")
    group_column = forms.CharField(max_length=120, required=False)
    value_column = forms.CharField(max_length=120, required=False)
    agg = forms.ChoiceField(choices=AGG_CHOICES, required=False, initial="count")
    sort_column = forms.CharField(max_length=120, required=False)
    n = forms.IntegerField(required=False, initial=100)
    ascending = forms.BooleanField(required=False, initial=False)
    subset_column = forms.CharField(max_length=120, required=False)
    columns = forms.CharField(max_length=500, required=False)
    drop = forms.BooleanField(required=False, initial=False)
    row_column = forms.CharField(max_length=120, required=False)
    column_column = forms.CharField(max_length=120, required=False)
    column_a = forms.CharField(max_length=120, required=False)
    operation = forms.ChoiceField(choices=OPERATION_CHOICES, required=False, initial="divide")
    operand = forms.CharField(max_length=120, required=False)
    group_by = forms.CharField(max_length=120, required=False)
    # Annotation
    new_column_name = forms.CharField(max_length=120, required=False)
    ngram = forms.IntegerField(required=False, initial=1)
    unit = forms.ChoiceField(choices=UNIT_CHOICES, required=False, initial="words")
    date_column = forms.CharField(max_length=120, required=False, initial="publish_time")
    # Visualization
    category_column = forms.CharField(max_length=120, required=False)
    series_column = forms.CharField(max_length=120, required=False)
    x_column = forms.CharField(max_length=120, required=False)
    y_column = forms.CharField(max_length=120, required=False)
    color_column = forms.CharField(max_length=120, required=False)
    size_column = forms.CharField(max_length=120, required=False)
    coord_column = forms.CharField(max_length=120, required=False, initial="2d")
    bins = forms.IntegerField(required=False, initial=30)
    top_n = forms.IntegerField(required=False, initial=25)
    chart_title = forms.CharField(max_length=200, required=False)
    exclude = forms.CharField(max_length=300, required=False)
    log_x = forms.BooleanField(required=False, initial=False)
    log_y = forms.BooleanField(required=False, initial=False)
    # Hierarchical clustering (agglomerate topics into super-clusters / dendrogram)
    n_clusters = forms.IntegerField(required=False, initial=10)
    orientation = forms.ChoiceField(
        choices=[("left", "left"), ("right", "right"), ("bottom", "bottom"), ("top", "top")],
        required=False, initial="left",
    )