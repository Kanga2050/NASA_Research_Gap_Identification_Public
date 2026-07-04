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
    ACTION_CHOICES = [
        ("embed_text", "Embed text"),
        ("reduce_dimensionality", "Reduce dimensionality"),
        ("cluster", "Cluster"),
        ("distance_map", "Distance map"),
        ("keyword_score", "Keyword score"),
        ("semantic_score", "Semantic score"),
        ("hybrid_score", "Hybrid score"),
        ("numerical_filter", "Numerical filter"),
        ("openalex_scraper", "OpenAlex scrape"),
    ]

    action = forms.ChoiceField(choices=ACTION_CHOICES)
    csv_name = forms.CharField(max_length=120, required=False)
    source_csv = forms.CharField(max_length=120, required=False)
    output_csv = forms.CharField(max_length=120, required=False)
    query = forms.CharField(max_length=300, required=False)
    topic = forms.CharField(max_length=300, required=False)
    text_column = forms.CharField(max_length=120, required=False, initial="abstract")
    embedding_column = forms.CharField(max_length=120, required=False, initial="abstract_embedding")
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