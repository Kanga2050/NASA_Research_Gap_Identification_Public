from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm
from django.core.exceptions import ImproperlyConfigured

from App.Backend import registry

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
    """The dashboard's "run a function" form.

    The fields below are the flat union of every argument any pipeline function takes
    -- the template shows only the ones the selected action uses. Which fields an
    action actually consumes, and in what order they reach the backend, is the
    registry's business, not this form's; the form only has to offer a widget for each
    of the registry's `form_field` names, which `_check_form_covers_registry` (below)
    enforces at import time.
    """

    AGG_CHOICES = [("count", "count"), ("mean", "mean"), ("sum", "sum"), ("min", "min"), ("max", "max")]
    UNIT_CHOICES = [("words", "words"), ("chars", "chars")]
    OPERATION_CHOICES = [("add", "add"), ("subtract", "subtract"), ("multiply", "multiply"), ("divide", "divide")]

    # Grouped by family so the dropdown reads in pipeline order (import -> annotate ->
    # distill -> visualize) rather than in whatever order the registry lists them.
    ACTION_CHOICES = [
        (category.title(), [(fn.name, fn.label) for fn in registry.by_category(category)])
        for category in ("annotation", "distillation", "visualization", "import")
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


def _check_form_covers_registry() -> None:
    """Fail loudly, at import, if a registry function needs a form field this form does
    not declare -- otherwise that argument would silently submit as blank and the task
    would run with a wrong default. This is the guard that lets the registry and the
    form be edited independently without them quietly drifting apart.
    """
    declared = set(TaskSubmitForm.base_fields)
    missing = {
        f"{fn.name}.{field}"
        for fn in registry.ALL_FUNCTIONS
        for field in fn.form_fields
        if field not in declared
    }
    if missing:
        raise ImproperlyConfigured(
            "TaskSubmitForm is missing a field for these registry params: "
            + ", ".join(sorted(missing))
        )


_check_form_covers_registry()