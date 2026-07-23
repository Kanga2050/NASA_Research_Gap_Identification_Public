"""Generate one Studio pipeline template per figure of the Comprehensive NLP
Analysis paper, tracing each chart back to the four source corpora.

Run with:
    python App/Frontend/manage.py shell < Data_Import/generate_figure_templates.py

Every template is built out of composite blocks (Data_Import/generate_figure_blocks.py),
so a figure's pipeline reads as the handful of steps that make it different, with the
shared machinery -- embedding and projection, topic discovery, the ten-probe emphasis
panel -- named rather than repeated. Each template carries the definition of every
block it uses, drawn on the canvas as a highlighted region beneath the pipeline, so the
file shows what its blocks ARE as well as where they are used, and stays runnable and
portable on its own.

Design rules (enforced by the companion audit):
  * Nothing dangles: a figure is one connected flow ending at its chart, with at most
    one "handoff" -- the last on-platform table, named in the description as the input
    to the agent-side step the node vocabulary cannot express (pivots, correlation
    matrices, AUC, momentum windows).
  * Where a derivation is off-platform, the chart reads a __csv__ bridge node named for
    that derived table, and the description says where it came from.
"""
import importlib.util
import sys

from django.contrib.auth import get_user_model

from App.Frontend.portal import studio_ops

_spec = importlib.util.spec_from_file_location(
    "figure_blocks",
    "/Users/schauha4/Desktop/Research_Gap_Identification/Data_Import/generate_figure_blocks.py")
figure_blocks = importlib.util.module_from_spec(_spec)
sys.modules["figure_blocks"] = figure_blocks
_spec.loader.exec_module(figure_blocks)

USER = get_user_model().objects.get(username="example")
BLOCKS = figure_blocks.build_all(USER)
THEMES = figure_blocks.THEMES
UNKNOWN_PROBE = figure_blocks.UNKNOWN_PROBE
SPECTER2 = figure_blocks.SPECTER2


# --------------------------------------------------------------------------- #
# graph builder
# --------------------------------------------------------------------------- #
class G:
    def __init__(self):
        self.nodes, self.edges, self._i = [], [], 0
        self.used = {}

    def n(self, action, ins=(), csv="", column="", ports=None, ports_out=None,
          def_of=None, **fields):
        self._i += 1
        nid = str(self._i)
        node = {"id": nid, "action": action, "csv": csv, "column": column, "fields": fields}
        if ports is not None:
            node["ports"] = ports
        if ports_out is not None:
            node["ports_out"] = ports_out
        if def_of:
            node["def_of"] = def_of
        self.nodes.append(node)
        for port, src in enumerate(ins):
            if src is None:
                continue
            from_port = 0
            if isinstance(src, tuple):
                src, from_port = src
            self.edges.append({"from": src, "to": nid, "toPort": port, "fromPort": from_port})
        return nid

    def block(self, name, ins=(), **params):
        """Place a block instance, and make sure this template carries its definition
        (and the definitions of any blocks that block is itself built from)."""
        self._ensure(name)
        return self.n("@" + name, ins=ins, **params)

    def _ensure(self, name):
        if name in self.used:
            return
        self.used[name] = BLOCKS[name]
        definition = BLOCKS[name]["definition"]
        remap = {}
        for node in definition["nodes"]:
            copy = dict(node)
            fields = dict(copy.pop("fields", {}) or {})
            remap[node["id"]] = self.n(node["action"], csv=copy.get("csv", ""),
                                       column=copy.get("column", ""),
                                       ports=copy.get("ports"), ports_out=copy.get("ports_out"),
                                       def_of=name, **fields)
            if node["action"].startswith("@"):
                self._ensure(node["action"][1:])
        for edge in definition["edges"]:
            self.edges.append({"from": remap[edge["from"]], "to": remap[edge["to"]],
                               "toPort": edge.get("toPort", 0),
                               "fromPort": edge.get("fromPort", 0)})

    def cols(self, table, *names):
        return [self.n("__column__", ins=[table], column=c) for c in names]

    def table(self, name, *columns):
        """A bridge: an agent-side derivation re-entering the graph as a source."""
        return self.cols(self.n("__csv__", csv=name), *columns)


def literature(g):
    """The OpenAlex harvest, embedded and projected."""
    csv = g.n("openalex_scraper", topic="space biology", limit=101273, csv_name="Space_Biology")
    text, = g.cols(csv, "text")
    project = g.block("Embed_And_Project", ins=[text])
    return csv, text, project


def pdf_corpus(g, folders, name, label):
    csv = g.n("chunk_pdfs", folders=folders, csv_name=name, source_label=label,
              chunk_words=250, overlap_words=40)
    text, = g.cols(csv, "text")
    return csv, text


def on_target(g):
    """The harvest narrowed to its relevance-scored core -- the table every temporal
    emphasis view is measured on."""
    csv, text, project = literature(g)
    relevance = g.block("Relevance_Score", ins=[text, (project, 0)])
    core = g.n("numerical_filter", ins=[csv, relevance], threshold="0.01",
               output_csv="Literature_OnTarget")
    return csv, text, project, core


# --------------------------------------------------------------------------- #
# the figures
# --------------------------------------------------------------------------- #
SPECS = []


def fig(num, name, description):
    def wrap(fn):
        SPECS.append((num, name, description, fn))
        return fn
    return wrap


BLOCK_NOTE = (" The pipeline is built from blocks; each one's definition is drawn as a "
              "highlighted region beneath it.")
EMPHASIS_NOTE = (" Theme_Emphasis scores every passage against the ten risk probes, averages "
                 "each within the grouping column, scales by the report's x1000 and stacks the "
                 "ten per-theme tables into one long (group, theme, emphasis) table.")
COVERAGE_HANDOFF = (" That long table is the handoff: it is mean-centred and pivoted to one row "
                    "per theme with a column per window (Coverage_Wide) agent-side, because the "
                    "node vocabulary can stack tables but not pivot them.")
TRAJ_NOTE = (" The harvest is narrowed to its on-target core by numerical_filter on hybrid "
             "favorability (n = 4,415) before the per-year means are taken.")


@fig(1, "SB_Distance_Map", "Figure 1. The 101,273-record OpenAlex literature harvest as a 2-D "
     "intertopic map. Embed_And_Project gives the SPECTER2 vectors and their UMAP projections; "
     "Topic_Model discovers the topics on the 5-D coordinates and names them; distance_map "
     "positions one bubble per topic at its mean 2-D coordinate." + BLOCK_NOTE)
def _f1(g):
    csv, text, project = literature(g)
    topics = g.block("Topic_Model", ins=[(project, 1), text])
    g.n("distance_map", ins=[(topics, 0), (topics, 1), (project, 2)],
        output_name="SB_Distance_Map",
        chart_title="Space Biology - Intertopic Distance Map (101,273 OpenAlex records)")


@fig(2, "SB_Favorability_Hist", "Figure 2. Signal-versus-noise in the literature harvest. "
     "Relevance_Score fuses TF-IDF keyword scoring with SPECTER2 cosine similarity by "
     "reciprocal-rank fusion; the histogram is drawn on a log count axis so the thin on-target "
     "tail is visible beside the near-zero bulk." + BLOCK_NOTE)
def _f2(g):
    csv, text, project = literature(g)
    relevance = g.block("Relevance_Score", ins=[text, (project, 0)])
    g.n("histogram", ins=[relevance], bins=50, log_y=True, output_name="SB_Favorability_Hist",
        chart_title="Space Biology - Distribution of Spaceflight-Relevance Scores (log count)")


@fig(3, "OSDR_Journals", "Figure 3. Publication venues of the OSDR open-data corpus. The 171 "
     "deposited-data PDFs are chunked by chunk_pdfs (Crossref enrichment supplies journal and "
     "title), then deduplicate on DOI collapses the 8,646 chunks back to one row per paper "
     "before the venue count. No embedding is involved - this figure is about provenance.")
def _f3(g):
    # no embedding here, so the corpus is placed directly rather than through pdf_corpus
    csv = g.n("chunk_pdfs", folders="OSDR_Pdfs", csv_name="OSDR", source_label="OSDR",
              chunk_words=250, overlap_words=40)
    doi, = g.cols(csv, "doi")
    papers = g.n("deduplicate", ins=[csv, doi], output_csv="OSDR_Papers")
    journal, = g.cols(papers, "journal")
    g.n("bar_chart", ins=[journal], top_n=20, output_name="OSDR_Journals",
        chart_title="OSDR - Journals Publishing NASA Open-Data Research (paper-level)")


@fig(4, "OSDR_Model_Organisms", "Figure 4. Model-organism profile of OSDR. Phrase_Counts sums the "
     "corpus-wide unigram counts (the handoff); the synonym sets for each model system - "
     "human/clinical, rodent, microbial, Arabidopsis, Drosophila, C. elegans, other - are summed "
     "from those counts agent-side into OSDR_Model_Organisms, which the bar chart reads.")
def _f4(g):
    csv, text = pdf_corpus(g, "OSDR_Pdfs", "OSDR", "OSDR")
    g.block("Phrase_Counts", ins=[csv, text], ngram=1, output_csv="OSDR_WordCounts")
    organism, mentions = g.table("OSDR_Model_Organisms", "organism", "mentions")
    g.n("bar_chart", ins=[organism, mentions], top_n=10, output_name="OSDR_Model_Organisms",
        chart_title="OSDR Open-Data Corpus - Mentions by Model Organism")


@fig(5, "Decadal_Top_Terms", "Figure 5. Characteristic vocabulary of the three National Academies "
     "Decadal Survey volumes. chunk_pdfs splits them into 2,580 passages and Phrase_Counts sums "
     "the unigrams across the corpus." + BLOCK_NOTE)
def _f5(g):
    csv, text = pdf_corpus(g, "Decadal_Survey_Pdfs", "Decadal_Survey", "Decadal Survey")
    counts = g.block("Phrase_Counts", ins=[csv, text], ngram=1, output_csv="Decadal_WordCounts")
    key, total = g.cols(counts, "key", "sum")
    g.n("bar_chart", ins=[key, total], top_n=30, output_name="Decadal_Top_Terms",
        chart_title="NASA Decadal Survey - Most Frequent Content Terms")


@fig(6, "TB_Collection_Compare", "Figure 6. The robustness check on the Task Book scrape. "
     "Taskbook_Portfolio parses both collections, stacks them with a collection tag and "
     "de-duplicates on task id; the grouped bar compares division composition between the search "
     "set (2,916 reports) and the bibliography set (5,571)." + BLOCK_NOTE)
def _f6(g):
    portfolio = g.block("Taskbook_Portfolio")
    division, collection = g.cols(portfolio, "division", "collection")
    g.n("bar_chart", ins=[division, None, collection], top_n=10,
        output_name="TB_Collection_Compare",
        chart_title="NASA Task Book - Division Composition, Search vs Bibliography Collections")


@fig(7, "TB_Top_Institutions", "Figure 7. Institutional base of the funded portfolio. Each Task "
     "Book PDF is parsed into one structured row (54 form labels); the merged, de-duplicated "
     "portfolio is counted by organization." + BLOCK_NOTE)
def _f7(g):
    portfolio = g.block("Taskbook_Portfolio")
    org, = g.cols(portfolio, "organization")
    g.n("bar_chart", ins=[org], top_n=15, output_name="TB_Top_Institutions",
        chart_title="NASA Task Book - Institutions with the Most Funded Projects")


@fig(8, "SB_Dendrogram", "Figure 8. Hierarchy of the literature's topics. Each topic is reduced "
     "to the centroid of its members' 5-D coordinates and the topics are joined by Ward linkage; "
     "the leaves are named from Topic_Model's label column. This is the view that shows the "
     "on-target cluster to be a peripheral leaf rather than a hub." + BLOCK_NOTE)
def _f8(g):
    csv, text, project = literature(g)
    topics = g.block("Topic_Model", ins=[(project, 1), text])
    g.n("hierarchical_dendrogram", ins=[(topics, 0), (topics, 1), (project, 1)], top_n=30,
        orientation="left", output_name="SB_Dendrogram",
        chart_title="Space Biology - Topic Hierarchy (Ward linkage over topic centroids)")


@fig(9, "OSDR_Dendrogram", "Figure 9. Hierarchy of the OSDR open-data corpus, built exactly as "
     "Figure 8 but over the 8,646 OSDR chunks." + BLOCK_NOTE)
def _f9(g):
    csv, text = pdf_corpus(g, "OSDR_Pdfs", "OSDR", "OSDR")
    project = g.block("Embed_And_Project", ins=[text])
    topics = g.block("Topic_Model", ins=[(project, 1), text])
    g.n("hierarchical_dendrogram", ins=[(topics, 0), (topics, 1), (project, 1)], top_n=25,
        orientation="left", output_name="OSDR_Dendrogram",
        chart_title="OSDR - Topic Hierarchy (Ward linkage over topic centroids)")


@fig(10, "Decadal_Dendrogram", "Figure 10. Hierarchy of the Decadal Survey priorities. The prose "
     "is homogeneous, so Topic_Model is run at finer resolution (min_cluster_size 10 / min_samples "
     "3) - the promoted parameters on the block instance - which is what resolves the "
     "human-physiology, physical-sciences and plant branches." + BLOCK_NOTE)
def _f10(g):
    csv, text = pdf_corpus(g, "Decadal_Survey_Pdfs", "Decadal_Survey", "Decadal Survey")
    project = g.block("Embed_And_Project", ins=[text])
    topics = g.block("Topic_Model", ins=[(project, 1), text],
                     min_cluster_size=10, min_samples=3)
    g.n("hierarchical_dendrogram", ins=[(topics, 0), (topics, 1), (project, 1)], top_n=25,
        orientation="left", output_name="Decadal_Dendrogram",
        chart_title="Decadal Survey - Topic Hierarchy at Fine Resolution")


@fig(11, "SB_SuperTheme_Sizes", "Figure 11. The nine super-themes. hierarchical_cluster cuts "
     "Topic_Model's topic tree into nine coarse clusters, so every paper belongs to exactly one, "
     "and label_topics names each cut. This mutually exclusive partition is what makes the "
     "share-of-output views (Figures 18-19) well defined." + BLOCK_NOTE)
def _f11(g):
    csv, text, project = literature(g)
    topics = g.block("Topic_Model", ins=[(project, 1), text])
    hcluster = g.n("hierarchical_cluster", ins=[(topics, 0), (project, 1)], n_clusters=9,
                   output_column="hcluster")
    super_label = g.n("label_topics", ins=[hcluster, text], new_column_name="Super_Label")
    g.n("bar_chart", ins=[super_label], top_n=12, exclude="-1",
        output_name="SB_SuperTheme_Sizes",
        chart_title="Space Biology - Nine Super-Themes by Paper Count")


def _four_corpus_emphasis(g, group="dataset"):
    """The shared spine of the cross-sectional figures: four corpora in one tagged
    table, embedded once, then the ten-probe emphasis panel."""
    corpora = g.block("Four_Corpora")
    text, tag = g.cols(corpora, "text", group)
    project = g.block("Embed_And_Project", ins=[text])
    return corpora, text, tag, project, g.block("Theme_Emphasis",
                                                ins=[corpora, tag, (project, 0)])


@fig(12, "TB_Coverage_4way", "Figure 12. The core cross-sectional result: the emphasis each of the "
     "four windows places on the ten spaceflight-risk themes. Four_Corpora stacks the literature, "
     "OSDR, Decadal and funded portfolios into one table tagged by corpus, and one embedding pass "
     "puts them in a single SPECTER2 space." + EMPHASIS_NOTE + " The two arithmetic nodes then "
     "remove each corpus' baseline the way the report's mean-centring does: each theme's share of "
     "its own corpus' total, minus the 1/10 a flat profile would give." + BLOCK_NOTE)
def _f12(g):
    corpora, text, tag, project, long = _four_corpus_emphasis(g)
    emphasis, = g.cols(long, "emphasis")
    share = g.n("arithmetic", ins=[long, emphasis], operation="divide", operand="emphasis",
                group_by="dataset", new_column_name="share", output_csv="Coverage_Share")
    share_col, = g.cols(share, "share")
    centred = g.n("arithmetic", ins=[share, share_col], operation="subtract", operand="0.1",
                  new_column_name="relative_emphasis", output_csv="Coverage_Centred")
    theme, value, dataset = g.cols(centred, "theme", "relative_emphasis", "dataset")
    g.n("bar_chart", ins=[theme, value, dataset], top_n=10, output_name="TB_Coverage_4way",
        chart_title="Four Windows on Ten Risks - Literature vs OSDR vs Decadal vs Funded")


@fig(13, "SB_Gap_Ranking", "Figure 13. The priority gap, ranked." + EMPHASIS_NOTE +
     COVERAGE_HANDOFF + " The arithmetic node then subtracts the literature column from the "
     "Decadal column to give the gap the bar chart sorts on." + BLOCK_NOTE)
def _f13(g):
    _four_corpus_emphasis(g)
    wide = g.n("__csv__", csv="Coverage_Wide")
    dec, = g.cols(wide, "Decadal")
    ranked = g.n("arithmetic", ins=[wide, dec], operation="subtract", operand="Literature",
                 new_column_name="gap", output_csv="Gap_Ranking")
    theme, gap = g.cols(ranked, "theme", "gap")
    g.n("bar_chart", ins=[theme, gap], top_n=15, output_name="SB_Gap_Ranking",
        chart_title="Priority-Literature Emphasis Gap by Risk Theme (Decadal - Literature)")


@fig(14, "SB_Priority_Alignment", "Figure 14. The priority-alignment map: literature emphasis (x) "
     "against Decadal emphasis (y), bubble size from the OSDR column; distance from the "
     "45-degree line is the gap of Figure 13." + EMPHASIS_NOTE + COVERAGE_HANDOFF)
def _f14(g):
    _four_corpus_emphasis(g)
    lit, dec, osd, theme = g.table("Coverage_Wide", "Literature", "Decadal", "OSDR", "theme")
    g.n("scatter_plot", ins=[lit, dec, theme, osd], output_name="SB_Priority_Alignment",
        chart_title="Priority-Alignment Map - Literature vs Decadal Emphasis per Theme")


@fig(15, "SB_Corpus_Correlation", "Figure 15. Does open data track the literature or the "
     "priorities? Per-theme OSDR emphasis against literature emphasis - the tight positive "
     "relationship is what shows reusable data accumulating where publishing already is."
     + EMPHASIS_NOTE + COVERAGE_HANDOFF)
def _f15(g):
    _four_corpus_emphasis(g)
    lit, osd, theme = g.table("Coverage_Wide", "Literature", "OSDR", "theme")
    g.n("scatter_plot", ins=[lit, osd, theme], output_name="SB_Corpus_Correlation",
        chart_title="Open Data vs Literature - Per-Theme Emphasis")


@fig(16, "TB_Funding_vs_Literature", "Figure 16. Funded emphasis against published emphasis. "
     "Because Four_Corpora stacks the Task Book into the same table as the three text corpora, "
     "the funded portfolio is scored by the same ten probes and compared as a fourth window."
     + EMPHASIS_NOTE + COVERAGE_HANDOFF)
def _f16(g):
    _four_corpus_emphasis(g)
    lit, funded, theme = g.table("TB_Coverage_Wide", "Literature", "Funded", "theme")
    g.n("scatter_plot", ins=[lit, funded, theme], output_name="TB_Funding_vs_Literature",
        chart_title="Funded vs Published Emphasis per Risk Theme")


@fig(17, "TB_Funding_vs_Priorities", "Figure 17. Funded emphasis against Decadal-priority "
     "emphasis (r = 0.94) - the same table as Figure 16, cut on two different columns."
     + EMPHASIS_NOTE + COVERAGE_HANDOFF)
def _f17(g):
    _four_corpus_emphasis(g)
    dec, funded, theme = g.table("TB_Coverage_Wide", "Decadal", "Funded", "theme")
    g.n("scatter_plot", ins=[dec, funded, theme], output_name="TB_Funding_vs_Priorities",
        chart_title="Funded vs Decadal-Priority Emphasis per Risk Theme")


def _super_themes(g):
    csv, text, project = literature(g)
    topics = g.block("Topic_Model", ins=[(project, 1), text])
    hcluster = g.n("hierarchical_cluster", ins=[(topics, 0), (project, 1)], n_clusters=9,
                   output_column="hcluster")
    super_label = g.n("label_topics", ins=[hcluster, text], new_column_name="Super_Label")
    publish, = g.cols(csv, "publish_time")
    year = g.n("extract_year", ins=[publish], new_column_name="year")
    return csv, super_label, year


@fig(18, "SB_Topic_Composition", "Figure 18. Share of each year's output by super-theme, "
     "1995-2024. The literature is cut into nine super-themes (Figure 11) and dated by "
     "extract_year; cross_tab gives the year-by-super-theme count matrix - the handoff - which is "
     "normalised to within-year shares agent-side for the 100%-stacked view." + BLOCK_NOTE)
def _f18(g):
    csv, super_label, year = _super_themes(g)
    g.n("cross_tab", ins=[csv, year, super_label], output_csv="SB_Super_Year_Wide")
    y, share, label = g.table("SB_Super_Year_Share", "year", "share", "Super_Label")
    g.n("stacked_area", ins=[y, share, label], top_n=9, output_name="SB_Topic_Composition",
        chart_title="Space Biology - Share of Yearly Output by Super-Theme (1995-2024)")


@fig(19, "SB_Absolute_Volume", "Figure 19. The same nine super-themes as absolute counts per year "
     "rather than shares - the view that shows total output quadrupling while composition stays "
     "flat. Same year-by-super-theme cross_tab as Figure 18, melted to long form instead of "
     "normalised." + BLOCK_NOTE)
def _f19(g):
    csv, super_label, year = _super_themes(g)
    g.n("cross_tab", ins=[csv, year, super_label], output_csv="SB_Super_Year_Wide")
    y, count, theme = g.table("SB_Super_Year_Named", "year", "count", "theme")
    g.n("line_chart", ins=[y, count, theme], output_name="SB_Absolute_Volume",
        chart_title="Space Biology - Absolute Output per Super-Theme per Year (1995-2024)")


@fig(20, "TB_Funding_Timeline", "Figure 20. Unique funded projects per fiscal year, stacked by "
     "division. Taskbook_Portfolio de-duplicates on task id so each award is counted once; "
     "extract_year turns the 'FY 2021' field into a number; one branch per division counts "
     "projects per year, and a single Combine CSVs stacks the four branches - tagging each row "
     "with the division table it came from, which is the series the stack is drawn on."
     + BLOCK_NOTE)
def _f20(g):
    portfolio = g.block("Taskbook_Portfolio")
    division, fiscal = g.cols(portfolio, "division", "fiscal_year")
    year = g.n("extract_year", ins=[fiscal], new_column_name="year")
    branches = []
    for name, value in [("Human_Research", "Human Research"),
                        ("Physical_Sciences", "Physical Sciences"),
                        ("Space_Biology_Division", "Space Biology"),
                        ("Human_Research_and_Space_Biology", "Human Research, Space Biology")]:
        part = g.n("categorical_filter", ins=[portfolio, division], expected_value=value,
                   output_csv=f"TB_{name}")
        branches.append(g.n("group_aggregate", ins=[part, year], agg="count", output_csv=name))
    stacked = g.n("combine_csvs", ins=branches, ports=len(branches), source_column="division",
                  output_csv="TB_Year_Division")
    y, count, series = g.cols(stacked, "year", "count", "division")
    g.n("stacked_area", ins=[y, count, series], top_n=6, output_name="TB_Funding_Timeline",
        chart_title="NASA Task Book - Unique Funded Projects per Fiscal Year by Division")


def _trajectory(g):
    """The temporal spine: the on-target literature, dated, through the emphasis panel."""
    csv, text, project, core = on_target(g)
    publish, = g.cols(core, "publish_time")
    year = g.n("extract_year", ins=[publish], new_column_name="year")
    return core, g.block("Theme_Emphasis", ins=[core, year, (project, 0)])


@fig(21, "SB_Theme_Trajectories", "Figure 21. Per-year semantic emphasis of the ten risk themes in "
     "the literature, 1995-2024 - the motion the composition chart hides." + TRAJ_NOTE
     + EMPHASIS_NOTE + BLOCK_NOTE)
def _f21(g):
    core, long = _trajectory(g)
    year, emphasis, theme = g.cols(long, "year", "emphasis", "theme")
    g.n("trajectory_chart", ins=[year, emphasis, theme], top_n=10,
        output_name="SB_Theme_Trajectories",
        chart_title="Semantic Emphasis Trajectories of Ten Risk Themes (1995-2024)")


@fig(22, "SB_Momentum_Bar", "Figure 22. Momentum, ranked: each theme's change in literature "
     "emphasis from the 1995-99 window to the 2020-24 window. The per-year emphasis table is the "
     "handoff - the two five-year window means and their difference are taken agent-side into "
     "Momentum_Ranking, since the node vocabulary has no windowed difference." + TRAJ_NOTE)
def _f22(g):
    _trajectory(g)
    theme, momentum = g.table("Momentum_Ranking", "theme", "momentum")
    g.n("bar_chart", ins=[theme, momentum], top_n=15, output_name="SB_Momentum_Bar",
        chart_title="Temporal Momentum of Literature Emphasis (1995-99 -> 2020-24)")


@fig(23, "SB_Radiation_Plant_Crossover", "Figure 23. The report's central empirical claim in "
     "miniature. This figure needs only two of the ten themes, so it instantiates the Emphasis_Probe "
     "unit twice - space radiation and plant/crops, each averaged per year - and stacks them, so "
     "the 2013 crossing is visible on its own axes." + TRAJ_NOTE + BLOCK_NOTE)
def _f23(g):
    csv, text, project, core = on_target(g)
    publish, = g.cols(core, "publish_time")
    year = g.n("extract_year", ins=[publish], new_column_name="year")
    parts = []
    for key, tag, query in THEMES:
        if tag not in ("radiation", "plant_crops"):
            continue
        parts.append(g.block("Emphasis_Probe", ins=[core, year, (project, 0)],
                             query=query, score_column=key, mean_column=f"{key}_mean", theme=tag))
    long = g.n("combine_csvs", ins=parts, ports=2, source_column="theme",
               output_csv="Radiation_Plant")
    y, emphasis, theme = g.cols(long, "year", "emphasis", "theme")
    g.n("line_chart", ins=[y, emphasis, theme], output_name="SB_Radiation_Plant_Crossover",
        chart_title="A Reversal: Space Radiation vs Plant/Crop Emphasis (1995-2024)")


@fig(24, "SB_Theme_Trajectories_Gap", "Figure 24. The widening gap, focused: the same per-year "
     "emphasis table as Figure 21, with the chart keeping the six mission-critical themes - "
     "rising plant/crops and omics against falling bone, cardiovascular, muscle and SANS."
     + TRAJ_NOTE + BLOCK_NOTE)
def _f24(g):
    core, long = _trajectory(g)
    year, emphasis, theme = g.cols(long, "year", "emphasis", "theme")
    g.n("trajectory_chart", ins=[year, emphasis, theme], top_n=6,
        output_name="SB_Theme_Trajectories_Gap",
        chart_title="The Widening Gap - Six Themes, 1995-2024")


@fig(25, "TB_Momentum_Funding_Lit", "Figure 25. Does the money chase fashion? The funded portfolio "
     "goes through the same emphasis panel as the literature, grouped by fiscal year."
     + EMPHASIS_NOTE + " That table is the handoff: the early (FY2004-2012) and recent "
     "(FY2016-2025) window means, and the shift between them, are taken agent-side and plotted "
     "against the literature shift of Figure 22." + BLOCK_NOTE)
def _f25(g):
    portfolio = g.block("Taskbook_Portfolio")
    text, fiscal = g.cols(portfolio, "text", "fiscal_year")
    year = g.n("extract_year", ins=[fiscal], new_column_name="year")
    project = g.block("Embed_And_Project", ins=[text])
    g.block("Theme_Emphasis", ins=[portfolio, year, (project, 0)])
    lit_m, fund_m, theme = g.table("TB_Momentum", "lit_momentum", "fund_momentum", "theme")
    g.n("scatter_plot", ins=[lit_m, fund_m, theme], output_name="TB_Momentum_Funding_Lit",
        chart_title="Funding Resists Fashion - Funded vs Literature Momentum per Theme")


@fig(26, "SB_Gap_Quadrant", "Figure 26. The synthesis map: the static priority gap of Figure 13 "
     "(vertical) crossed with the temporal momentum of Figure 22 (horizontal), bubble size "
     "scaling with the theme's absolute literature emphasis." + EMPHASIS_NOTE + COVERAGE_HANDOFF)
def _f26(g):
    _four_corpus_emphasis(g)
    momentum, gap, theme, lit = g.table("Coverage_Wide", "momentum", "gap", "theme", "Literature")
    g.n("scatter_plot", ins=[momentum, gap, theme, lit], output_name="SB_Gap_Quadrant",
        chart_title="Synthesis Map - Priority Gap vs Temporal Momentum")


@fig(27, "OSDR_Bigrams_Bar", "Figure 27. OSDR's phrase fingerprint. Phrase_Counts with the n-gram "
     "promoted to 2 counts bigrams per chunk and sums them across the corpus - the "
     "transcriptomics-plus-experimental-design vocabulary of reusable mechanistic evidence."
     + BLOCK_NOTE)
def _f27(g):
    csv, text = pdf_corpus(g, "OSDR_Pdfs", "OSDR", "OSDR")
    counts = g.block("Phrase_Counts", ins=[csv, text], ngram=2, output_csv="OSDR_Bigrams")
    key, total = g.cols(counts, "key", "sum")
    g.n("bar_chart", ins=[key, total], top_n=25, output_name="OSDR_Bigrams_Bar",
        chart_title="OSDR - Most Frequent Bigrams")


@fig(28, "Decadal_Bigrams_Bar", "Figure 28. The Decadal Survey's phrase fingerprint, built the "
     "same way as Figure 27 over the 2,580 strategy passages - 'physical sciences' leads, which "
     "is the evidence that the surveys' remit is broader than biology." + BLOCK_NOTE)
def _f28(g):
    csv, text = pdf_corpus(g, "Decadal_Survey_Pdfs", "Decadal_Survey", "Decadal Survey")
    counts = g.block("Phrase_Counts", ins=[csv, text], ngram=2, output_csv="Decadal_Bigrams")
    key, total = g.cols(counts, "key", "sum")
    g.n("bar_chart", ins=[key, total], top_n=25, output_name="Decadal_Bigrams_Bar",
        chart_title="Decadal Survey - Most Frequent Bigrams")


@fig(29, "SB_Plants_Bigrams_Bar", "Figure 29. The plant surge, up close. The literature is cut "
     "into super-themes, categorical_filter keeps only the plant super-theme (3,216 papers), and "
     "Phrase_Counts counts its bigrams - showing Arabidopsis genomics and DNA barcoding rather "
     "than the applied crop production a Mars mission needs." + BLOCK_NOTE)
def _f29(g):
    csv, text, project = literature(g)
    topics = g.block("Topic_Model", ins=[(project, 1), text])
    hcluster = g.n("hierarchical_cluster", ins=[(topics, 0), (project, 1)], n_clusters=9,
                   output_column="hcluster")
    super_label = g.n("label_topics", ins=[hcluster, text], new_column_name="Super_Label")
    plants = g.n("categorical_filter", ins=[csv, super_label],
                 expected_value="plant, et, al, species", output_csv="SB_Plants")
    plant_text, = g.cols(plants, "text")
    counts = g.block("Phrase_Counts", ins=[plants, plant_text], ngram=2,
                     output_csv="SB_Plants_Bigrams")
    key, total = g.cols(counts, "key", "sum")
    g.n("bar_chart", ins=[key, total], top_n=25, output_name="SB_Plants_Bigrams_Bar",
        chart_title="Literature Plant Super-Theme - Most Frequent Bigrams")


@fig(30, "SB_Theme_CoOccurrence", "Figure 30. Which risks are studied together. Theme_Scores "
     "scores the on-target literature (n = 4,415) against the ten probes and projects them into "
     "the per-paper profile table - the handoff. Each paper's own mean across the ten is then "
     "subtracted agent-side to remove the 'how on-topic is this paper at all' factor, and the "
     "10x10 correlation of those relative profiles becomes the matrix behind the heatmap."
     + BLOCK_NOTE)
def _f30(g):
    csv, text, project, core = on_target(g)
    g.block("Theme_Scores", ins=[core, (project, 0)])
    a, b, r = g.table("Theme_Correlation_Long", "theme_a", "theme_b", "r")
    g.n("heatmap", ins=[a, b, r], output_name="SB_Theme_CoOccurrence",
        chart_title="Within-Paper Co-Emphasis Correlation of the Ten Risk Themes")


@fig(31, "SB_Theme_Network", "Figure 31. The same correlation matrix as Figure 30 rendered as a "
     "force-directed network: one edge per theme pair weighted by the correlation, with greedy "
     "modularity communities and momentum colouring applied on top. This is the view in which the "
     "falling human-physiology risks resolve into a single connected community." + BLOCK_NOTE)
def _f31(g):
    csv, text, project, core = on_target(g)
    g.block("Theme_Scores", ins=[core, (project, 0)])
    a, b, r = g.table("Theme_Correlation_Long", "theme_a", "theme_b", "r")
    g.n("network_graph", ins=[a, b, r], top_n=20, output_name="SB_Theme_Network",
        chart_title="The Field's Risk Communities - Theme Co-Occurrence Network")


@fig(32, "SB_Momentum_Acceleration", "Figure 32. Is the divergence slowing? Each theme's 30-year "
     "momentum is split into an early half (1995-99 -> 2015-19) and a recent half (2015-19 -> "
     "2020-24) from the per-year emphasis table - the handoff - and the two are plotted against "
     "each other with the full 30-year change as colour." + TRAJ_NOTE)
def _f32(g):
    _trajectory(g)
    early, recent, theme = g.table("Momentum_Acceleration", "early", "recent", "theme")
    g.n("scatter_plot", ins=[early, recent, theme], output_name="SB_Momentum_Acceleration",
        chart_title="Acceleration - Early vs Recent Emphasis Momentum per Theme")


@fig(33, "SB_Frontier_Map", "Figure 33. The frontier landscape. Unknown_Scores scores the harvest "
     "against the acknowledged-unknown probe, and numerical_filter keeps the 10,499 papers that "
     "pass the explicit cue criterion on the lexical score - the one Figure 35 shows to be fit for "
     "the purpose. That subset is re-clustered (min_cluster_size 20 / min_samples 4) over the 5-D "
     "coordinates it inherits, and mapped in the same 2-D projection as Figure 1." + BLOCK_NOTE)
def _f33(g):
    csv, text, project = literature(g)
    unknown = g.block("Unknown_Scores", ins=[text, (project, 0)])
    frontier = g.n("numerical_filter", ins=[csv, (unknown, 0)], threshold="0.02",
                   output_csv="SB_Frontier")
    ftext, f5d, f2d = g.cols(frontier, "text", "5d", "2d")
    topics = g.block("Topic_Model", ins=[f5d, ftext], min_cluster_size=20, min_samples=4)
    g.n("distance_map", ins=[(topics, 0), (topics, 1), f2d], output_name="SB_Frontier_Map",
        chart_title="The Frontier Landscape - 10,499 Hedged Papers, 72 Topics")


@fig(34, "Frontier_Density", "Figure 34. Genre, not virtue: how much of each window admits an "
     "unknown at all. All four corpora are stacked into one tagged table and scored by "
     "Unknown_Scores, and group_aggregate summarises the cue score per corpus - the handoff. The "
     "chart reads the cue-phrase share, counted agent-side from that same scored table, because "
     "the platform has no boolean-cue counter." + BLOCK_NOTE)
def _f34(g):
    corpora = g.block("Four_Corpora")
    text, dataset = g.cols(corpora, "text", "dataset")
    project = g.block("Embed_And_Project", ins=[text])
    unknown = g.block("Unknown_Scores", ins=[text, (project, 0)])
    g.n("group_aggregate", ins=[corpora, dataset, (unknown, 0)], agg="mean",
        output_csv="Frontier_Score_By_Corpus")
    corpus, density = g.table("Frontier_Density_Table", "corpus", "density")
    g.n("bar_chart", ins=[corpus, density], top_n=4, output_name="Frontier_Density",
        chart_title="Share of Each Corpus Carrying an Acknowledged-Unknown Cue")


@fig(35, "Frontier_Retrieval", "Figure 35. The retrieval diagnostic that chose the instrument. "
     "Unknown_Scores is exactly the three-way scoring under test - TF-IDF, SPECTER2 and their "
     "reciprocal-rank fusion - and group_aggregate summarises them per corpus (the handoff). Each "
     "method is then graded by AUC against the auditable cue-phrase ground truth agent-side: "
     "semantic scoring barely beats chance and the hybrid lands below keyword alone, which is why "
     "the rest of section 5 is lexical." + BLOCK_NOTE)
def _f35(g):
    corpora = g.block("Four_Corpora")
    text, dataset = g.cols(corpora, "text", "dataset")
    project = g.block("Embed_And_Project", ins=[text])
    unknown = g.block("Unknown_Scores", ins=[text, (project, 0)])
    g.n("group_aggregate", ins=[corpora, dataset, (unknown, 1)], agg="mean",
        output_csv="Frontier_Retrieval_Diagnostic")
    corpus, auc, method = g.table("Frontier_Retrieval_Long", "corpus", "auc", "method")
    g.n("bar_chart", ins=[corpus, auc, method], top_n=4, output_name="Frontier_Retrieval",
        chart_title="AUC for Retrieving Hedged Passages, by Scoring Method and Corpus")


def _openness(g):
    """Both lenses over the same four-corpus table: the ten theme probes for emphasis,
    and the acknowledged-unknown cue for openness."""
    corpora = g.block("Four_Corpora")
    text, dataset = g.cols(corpora, "text", "dataset")
    project = g.block("Embed_And_Project", ins=[text])
    g.block("Unknown_Scores", ins=[text, (project, 0)])
    return g.block("Theme_Emphasis", ins=[corpora, dataset, (project, 0)])


@fig(36, "Frontier_Openness_4way", "Figure 36. Openness lift across all four windows: for each "
     "theme, the open-question rate among that corpus' most theme-leaning quarter minus the "
     "corpus' own baseline. It needs both pipelines at once - the ten theme probes to rank each "
     "passage's relative emphasis, and the acknowledged-unknown cue to mark it open. The emphasis "
     "table is the handoff; the quartile cut and its confidence intervals are computed "
     "agent-side." + BLOCK_NOTE)
def _f36(g):
    _openness(g)
    theme, corpus, lift = g.table("Frontier_Openness_Long", "theme", "corpus", "lift")
    g.n("heatmap", ins=[theme, corpus, lift], output_name="Frontier_Openness_4way",
        chart_title="Openness Lift per Theme, Across All Four Windows (percentage points)")


@fig(37, "Frontier_vs_Momentum", "Figure 37. Candour runs backwards to momentum (r = -0.42): the "
     "literature's openness lift against its 30-year emphasis momentum. Both axes come from the "
     "same scored corpus - the theme probes for emphasis, the acknowledged-unknown cue for "
     "openness - and Frontier_Wide is assembled from that handoff agent-side." + BLOCK_NOTE)
def _f37(g):
    _openness(g)
    momentum, lift, theme = g.table("Frontier_Wide", "momentum", "Literature_lift", "theme")
    g.n("scatter_plot", ins=[momentum, lift, theme], output_name="Frontier_vs_Momentum",
        chart_title="Openness Lift vs 30-Year Emphasis Momentum")


@fig(38, "Frontier_vs_Funded", "Figure 38. The money is aimed at the acknowledged unknowns "
     "(r = +0.54): literature openness lift against funded emphasis. Because all four windows sit "
     "in one tagged table, the funded emphasis and the literature's openness come out of the same "
     "pipeline." + BLOCK_NOTE)
def _f38(g):
    _openness(g)
    funded, lift, theme = g.table("Frontier_Wide", "Funded", "Literature_lift", "theme")
    g.n("scatter_plot", ins=[funded, lift, theme], output_name="Frontier_vs_Funded",
        chart_title="Openness Lift vs Funded Emphasis per Theme")


@fig(39, "SB_Trajectories_Annotated", "Figure 39. The timeline, drawn: the same per-year emphasis "
     "table as Figure 21 (the chart keeps its five largest series) with the programmes, "
     "facilities and landmark publications of the hand-built, source-validated event timeline "
     "overlaid as dated markers when the paper is built." + TRAJ_NOTE + BLOCK_NOTE)
def _f39(g):
    core, long = _trajectory(g)
    year, emphasis, theme = g.cols(long, "year", "emphasis", "theme")
    g.n("trajectory_chart", ins=[year, emphasis, theme], top_n=5,
        output_name="SB_Trajectories_Annotated",
        chart_title="Emphasis Trajectories Against the Historical Record")


@fig(40, "SB_Sequencing_Omics", "Figure 40. The molecular tide is exogenous. Like Figure 23 this "
     "needs only two themes - omics and microbiome - so it instantiates the Emphasis_Probe unit "
     "twice; NHGRI's published cost-per-genome curve is an external reference series, not one of "
     "the four corpora, and is overlaid on the second axis when the paper is built."
     + TRAJ_NOTE + BLOCK_NOTE)
def _f40(g):
    csv, text, project, core = on_target(g)
    publish, = g.cols(core, "publish_time")
    year = g.n("extract_year", ins=[publish], new_column_name="year")
    parts = []
    for key, tag, query in THEMES:
        if tag not in ("omics", "microbiome"):
            continue
        parts.append(g.block("Emphasis_Probe", ins=[core, year, (project, 0)],
                             query=query, score_column=key, mean_column=f"{key}_mean", theme=tag))
    long = g.n("combine_csvs", ins=parts, ports=2, source_column="theme",
               output_csv="Omics_Microbiome_By_Year")
    y, emphasis, theme = g.cols(long, "year", "emphasis", "theme")
    g.n("line_chart", ins=[y, emphasis, theme], output_name="SB_Sequencing_Omics",
        chart_title="Omics & Microbiome Emphasis vs NHGRI Cost per Genome")


# --------------------------------------------------------------------------- #
# write them
# --------------------------------------------------------------------------- #
for num, name, description, build in sorted(SPECS):
    g = G()
    build(g)
    result = studio_ops.write_graph(USER, "Fig%02d_%s" % (num, name), g.nodes, g.edges,
                                    description=description, blocks=g.used or None)
    pipeline = len([n for n in g.nodes if not n.get("def_of")])
    print("%-40s %2d nodes (%2d pipeline) blocks: %s"
          % (result["name"], len(g.nodes), pipeline, ", ".join(sorted(g.used)) or "-"))
print("total templates:", len(SPECS), "| blocks:", len(BLOCKS))
